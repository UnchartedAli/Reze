"""Run plugins in separate processes (the isolated plugin host).

What this gives you
* An isolated plugin runs in its own Python process, with a clean environment
  (no REZE_* variables, no tokens) and only the standard library available.
* It cannot touch the bot's objects, database connection or Telegram client.
* Its only capability is ``reply``, and only when it declares ``telegram.message``.
* Every call has a timeout. Output is clipped. A crash or hang stops that plugin
  only. The bot keeps running.
* The plugin file is hashed when first approved. A later change is refused until
  someone approves it again.

What this does NOT give you
* It is not a sandbox against hostile code. The worker runs as the same operating
  system user and can read files that user can read, including the database file.
  Treat isolation as a way to contain bugs and limit accidental access. Do not
  run code you do not trust.
* Memory and CPU limits apply on POSIX systems only (``resource``). On Windows
  the timeout and the process boundary still apply, but the limits do not.
* Only ``reply`` is offered. More capabilities need their own permission and code.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from reze.command_router import router
from reze.database import db
from reze.exceptions import ManifestError
from reze.logging_config import logger
from reze.plugins.manifest import build_manifest

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")
MAX_LINE = 256 * 1024
SAFE_ENV_KEYS = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME")
REPLY_PERMISSION = "telegram.message"
MAX_REPLIES_PER_CALL = 5
MAX_RESTARTS = 5
APPROVAL_KEY = "plugin.isolated.sha256."


class IsolationError(RuntimeError):
    """A problem with an isolated plugin. The message is safe to show the owner."""


class PluginFailure(IsolationError):
    """The plugin raised an exception. The worker is still healthy, so it is not restarted."""


class _Timeout(Exception):
    pass


@dataclass(frozen=True)
class Limits:
    call_timeout: float = 5.0
    start_timeout: float = 5.0
    max_output: int = 3000
    memory_mb: int = 512
    cpu_seconds: int = 20


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _posix_limits(limits: Limits) -> Optional[Callable[[], None]]:
    if os.name != "posix":
        return None
    import resource

    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_mb * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds,) * 2)

    return apply


def _clean_env() -> Dict[str, str]:
    env = {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class IsolatedPlugin:
    """One plugin, one worker process."""

    def __init__(self, name: str, path: str, limits: Limits = Limits()) -> None:
        self.name = name
        self.path = os.path.abspath(path)
        self.limits = limits
        self.manifest = None
        self.commands: List[str] = []
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.restarts = 0
        self._workdir: Optional[str] = None
        self._stderr_task: Optional[asyncio.Task] = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> None:
        if self.running:
            return
        self._workdir = tempfile.mkdtemp(prefix=f"reze-plugin-{self.name}-")
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-S", WORKER, self.path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_clean_env(),
            cwd=self._workdir,
            limit=MAX_LINE,
            preexec_fn=_posix_limits(self.limits),
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        # The worker announces itself with "loaded" once the plugin has been imported.
        message = await self._read(self.limits.start_timeout)
        if message.get("type") != "loaded":
            await self.stop()
            raise IsolationError(str(message.get("message", "the plugin did not load"))[:300])
        self.manifest = message.get("manifest") or {}
        self.commands = [str(item) for item in message.get("commands") or []]

    async def _drain_stderr(self) -> None:
        """Read the plugin's stderr so the pipe never fills. Only a short, truncated prefix is logged."""
        assert self.proc is not None and self.proc.stderr is not None
        lines = 0
        while True:
            raw = await self.proc.stderr.readline()
            if not raw:
                return
            lines += 1
            if lines <= 50:
                logger.debug("plugin %s: %s", self.name, raw[:200].decode("utf-8", "replace").rstrip())

    async def _write(self, message: Dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise IsolationError("The plugin process is not running.")
        self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

    async def _read(self, timeout: float) -> Dict[str, Any]:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            raw = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
        except asyncio.TimeoutError as exc:
            raise _Timeout() from exc
        except (ValueError, asyncio.LimitOverrunError) as exc:
            raise IsolationError("The plugin sent a message that is too large.") from exc
        if not raw:
            code = self.proc.returncode if self.proc.returncode is not None else await self.proc.wait()
            raise IsolationError(f"The plugin process exited (code {code}).")
        try:
            message = json.loads(raw)
        except ValueError as exc:
            raise IsolationError("The plugin sent malformed data.") from exc
        if not isinstance(message, dict):
            raise IsolationError("The plugin sent malformed data.")
        return message

    async def call(self, command: str, payload: Dict[str, Any], host: Callable[[str, Dict[str, Any]], Awaitable[Any]]) -> str:
        if not self.running:
            raise IsolationError("The plugin process is not running.")
        await self._write({"type": "call", "command": command, "payload": payload})
        replies = 0
        try:
            while True:
                message = await self._read(self.limits.call_timeout)
                kind = message.get("type")
                if kind == "host":
                    replies += 1
                    if replies > MAX_REPLIES_PER_CALL:
                        raise IsolationError("The plugin sent too many replies in one call.")
                    try:
                        value = await host(str(message.get("op", "")), dict(message.get("payload") or {}))
                        await self._write({"type": "host_result", "ok": True, "value": value})
                    except PermissionError as exc:
                        await self._write({"type": "host_result", "ok": False, "error": str(exc)[:200]})
                    continue
                if kind == "result":
                    return _clip(str(message.get("value", "")), self.limits.max_output)
                if kind == "error":
                    raise PluginFailure(str(message.get("message", "plugin error"))[:300])
                raise IsolationError("The plugin sent an unexpected message.")
        except _Timeout:
            await self.stop()
            raise IsolationError("The plugin took too long and was stopped.")
        except PluginFailure:
            raise  # a contained error inside the plugin; the worker keeps running
        except IsolationError:
            await self.stop()
            raise

    async def stop(self) -> None:
        proc = self.proc
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                logger.warning("plugin %s did not exit after kill", self.name)
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._workdir:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


class IsolatedPluginHost:
    """Loads isolated plugins, registers their commands, and checks their approval."""

    def __init__(self, limits: Limits = Limits()) -> None:
        self.limits = limits
        self.plugins: Dict[str, IsolatedPlugin] = {}

    # ------------------------------------------------------------ approval
    @staticmethod
    def approve(name: str, path: str) -> str:
        digest = file_sha256(path)
        db.set_setting(APPROVAL_KEY + name, digest)
        return digest

    @staticmethod
    def approved_hash(name: str) -> Optional[str]:
        return db.get_setting(APPROVAL_KEY + name, None)

    @staticmethod
    def forget_approval(name: str) -> None:
        db.delete_setting(APPROVAL_KEY + name)

    # ------------------------------------------------------------- loading
    async def load(self, name: str, path: str) -> List[str]:
        """Start the plugin, validate it, and register its commands. Returns the command names."""
        if name in self.plugins:
            raise IsolationError(f"Plugin '{name}' is already loaded.")
        current = file_sha256(path)
        recorded = self.approved_hash(name)
        first_use = recorded is None
        if not first_use and recorded != current:
            raise IsolationError(
                f"Plugin '{name}' changed since it was approved. Review the file, then approve it again."
            )

        plugin = IsolatedPlugin(name, path, self.limits)
        try:
            await plugin.start()
            manifest = build_manifest(plugin.manifest, fallback_id=name)
        except ManifestError as exc:
            await plugin.stop()
            raise IsolationError(str(exc)[:300]) from exc
        except IsolationError:
            await plugin.stop()
            raise

        undeclared = [command for command in plugin.commands if command not in manifest.commands]
        if undeclared:
            await plugin.stop()
            raise IsolationError("Registers commands the manifest does not declare: " + ", ".join(undeclared))
        missing = [command for command in manifest.commands if command not in plugin.commands]
        if missing:
            await plugin.stop()
            raise IsolationError("Declares commands that were not registered: " + ", ".join(missing))

        collisions = [command for command in plugin.commands if command in router.commands]
        if collisions:
            await plugin.stop()
            raise IsolationError("Command names already in use: " + ", ".join(collisions))

        self.plugins[name] = plugin
        plugin.permissions = tuple(manifest.permissions)
        if first_use:
            # Approve only a plugin that passed every check above.
            self.approve(name, path)
            logger.info("Isolated plugin '%s' approved on first load (sha256 %s…).", name, current[:12])
        for command in plugin.commands:
            router.register(
                name=command,
                category="Plugins",
                description=f"Isolated plugin '{name}'.",
                usage=f".{command}",
                permissions=tuple(manifest.permissions),
            )(self._handler(name, command))
            router.commands[command].plugin = name
        logger.info("Isolated plugin '%s' loaded with %d command(s).", name, len(plugin.commands))
        return list(plugin.commands)

    def _handler(self, name: str, command: str):
        async def handler(ctx):
            text = await self.invoke(name, command, ctx)
            if text:
                return await ctx.reply(text)
            return None

        handler.__name__ = f"isolated_{name}_{command}"
        return handler

    async def invoke(self, name: str, command: str, ctx: Any) -> str:
        plugin = self.plugins.get(name)
        if plugin is None:
            raise IsolationError(f"Plugin '{name}' is not loaded.")
        if not plugin.running:
            if plugin.restarts >= MAX_RESTARTS:
                raise IsolationError(f"Plugin '{name}' crashed too often and stays stopped until it is reloaded.")
            plugin.restarts += 1
            await plugin.start()

        async def host(op: str, payload: Dict[str, Any]) -> Any:
            return await self._host_operation(plugin, ctx, op, payload)

        payload = {
            "args": [str(item) for item in getattr(ctx, "args", [])][:50],
            "text": str(getattr(ctx, "text", "") or "")[:2000],
            "sender_id": getattr(ctx, "sender_id", None),
        }
        return await plugin.call(command, payload, host)

    async def _host_operation(self, plugin: IsolatedPlugin, ctx: Any, op: str, payload: Dict[str, Any]) -> Any:
        if op == "reply":
            if REPLY_PERMISSION not in getattr(plugin, "permissions", ()):
                raise PermissionError(f"The plugin did not declare '{REPLY_PERMISSION}'.")
            await ctx.reply(str(payload.get("text", ""))[:4000])
            return True
        raise PermissionError(f"Unknown or unsupported operation: {op[:40]}")

    # ------------------------------------------------------------ unloading
    async def unload(self, name: str) -> bool:
        plugin = self.plugins.pop(name, None)
        if plugin is None:
            return False
        for command in plugin.commands:
            router.commands.pop(command, None)
        await plugin.stop()
        logger.info("Isolated plugin '%s' unloaded.", name)
        return True

    async def shutdown(self) -> None:
        for name in list(self.plugins):
            await self.unload(name)


__all__ = ["IsolatedPlugin", "IsolatedPluginHost", "IsolationError", "Limits", "PluginFailure", "file_sha256"]
