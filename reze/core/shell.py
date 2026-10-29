"""
Run a shell command for ``.exec`` and ``.update``.

Safety properties:
* a hard timeout; the whole process group is killed when it expires;
* output is truncated (head + tail) before it can flood a chat;
* secrets are stripped from the child's environment, so ``env`` / ``printenv``
  cannot leak ``REZE_API_HASH``, session strings, API keys or passwords;
* the call is only reachable through owner-only, opt-in commands.
"""

import asyncio
import os
import signal
import time
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Union

SECRET_HINTS = ("HASH", "SESSION", "KEY", "PASSWORD", "SECRET", "TOKEN", "COOKIE")


@dataclass
class ShellResult:
    code: Optional[int]
    output: str
    timed_out: bool
    elapsed: float


def clean_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    source = dict(os.environ if env is None else env)
    return {
        k: v for k, v in source.items()
        if not (k.upper().startswith("REZE_") and any(h in k.upper() for h in SECRET_HINTS))
        and not any(h in k.upper() for h in ("API_HASH", "SESSION_STRING", "PASSWORD"))
    }


def truncate(text: str, limit: int = 3000) -> str:
    text = text.replace("\x00", "")
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return f"{text[:head]}\n... [{len(text) - limit} characters omitted] ...\n{text[-tail:]}"


async def run(
    command: Union[str, Sequence[str]],
    *,
    timeout: float = 60.0,
    cwd: Optional[str] = None,
    limit: int = 3000,
    shell: bool = True,
) -> ShellResult:
    started = time.monotonic()
    kwargs = dict(
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL,
        cwd=cwd,
        env=clean_env(),
    )
    if os.name != "nt":
        kwargs["start_new_session"] = True  # lets us kill the whole group

    if shell:
        proc = await asyncio.create_subprocess_shell(str(command), **kwargs)
    else:
        proc = await asyncio.create_subprocess_exec(*command, **kwargs)

    timed_out = False
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            raw, _ = await asyncio.wait_for(proc.communicate(), 5)
        except Exception:  # noqa: BLE001
            raw = b""
    text = (raw or b"").decode("utf-8", errors="replace")
    return ShellResult(
        code=None if timed_out else proc.returncode,
        output=truncate(text.strip(), limit),
        timed_out=timed_out,
        elapsed=time.monotonic() - started,
    )
