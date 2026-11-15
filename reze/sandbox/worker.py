"""Worker process for isolated plugins. Standard library only.

Started by ``reze.sandbox.isolation`` as::

    python -I -S worker.py <plugin.py>

``-I`` ignores environment variables and user site-packages; ``-S`` skips site
initialisation. This file imports nothing from REZE, so an isolated plugin cannot
reach the bot's database, Telegram client or settings through this process.

Protocol: one JSON object per line. The host writes requests on stdin and reads
responses on stdout. Anything a plugin prints goes to stderr, so it can never
corrupt the channel.

Plugins use the ``reze_sdk`` module, provided here::

    from reze_sdk import command
    MANIFEST = {"id": "demo", "version": "1.0.0", "permissions": ["telegram.message"], "commands": ["demo"]}

    @command("demo")
    def demo(ctx):
        ctx.reply("hello")       # needs telegram.message
        return "done"            # sent as the final reply
"""

import json
import sys
import types

PROTOCOL = 1
_commands = {}
_protocol_out = sys.stdout.buffer
_protocol_in = sys.stdin.buffer
sys.stdout = sys.stderr  # print() from a plugin must not reach the protocol channel


class HostDenied(RuntimeError):
    """The host refused an operation (for example, a permission the plugin did not declare)."""


def _send(message):
    _protocol_out.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
    _protocol_out.flush()


def _host_request(op, payload):
    _send({"type": "host", "op": op, "payload": payload})
    line = _protocol_in.readline()
    if not line:
        raise SystemExit(0)  # the host went away: exit quietly
    response = json.loads(line)
    if response.get("ok"):
        return response.get("value")
    raise HostDenied(str(response.get("error", "denied")))


class Context:
    """What a command receives. Input is read-only; output goes through the host."""

    def __init__(self, payload):
        self.args = list(payload.get("args") or [])
        self.text = str(payload.get("text") or "")
        self.sender_id = payload.get("sender_id")

    def reply(self, text):
        return _host_request("reply", {"text": str(text)[:4000]})


def command(name, *, description="", usage=""):
    def decorate(function):
        _commands[name] = {"function": function, "description": description, "usage": usage}
        return function

    return decorate


sdk = types.ModuleType("reze_sdk")
sdk.command = command
sdk.Context = Context
sdk.PROTOCOL = PROTOCOL
sys.modules["reze_sdk"] = sdk


def _load(path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("isolated_plugin", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot create an import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = getattr(module, "MANIFEST", None)
    if not isinstance(manifest, dict):
        raise RuntimeError("the plugin must define MANIFEST as a dictionary")
    json.dumps(manifest)  # must be plain data
    return manifest


def main(argv):
    if len(argv) != 2:
        return 2
    try:
        manifest = _load(argv[1])
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - report every load failure to the host
        _send({"type": "error", "message": f"load failed: {type(exc).__name__}: {str(exc)[:200]}"})
        return 1
    _send({"type": "loaded", "manifest": manifest, "commands": sorted(_commands)})

    while True:
        line = _protocol_in.readline()
        if not line:
            return 0
        try:
            message = json.loads(line)
        except ValueError:
            _send({"type": "error", "message": "malformed request"})
            continue
        if message.get("type") != "call":
            _send({"type": "error", "message": "unknown request"})
            continue
        entry = _commands.get(str(message.get("command", "")))
        if entry is None:
            _send({"type": "error", "message": "unknown command"})
            continue
        try:
            value = entry["function"](Context(message.get("payload") or {}))
            _send({"type": "result", "value": "" if value is None else str(value)})
        except SystemExit:
            raise
        except BaseException as exc:  # noqa: BLE001 - a plugin error must not end the worker
            _send({"type": "error", "message": f"{type(exc).__name__}: {str(exc)[:200]}"})


if __name__ == "__main__":
    sys.exit(main(sys.argv))
