# Plugin developer guide

Reze plugins are Python files in `reze/plugins/` that register commands with the
shared router and export a manifest.

## 1. Minimal plugin

```python
from reze.command_router import CommandContext, router
from reze.ui import ascii

MANIFEST = {
    "name": "Greeting",
    "id": "greeting",
    "version": "1.0.0",
    "description": "Says hello in the current theme.",
    "author": "you",
    "source": "https://example.com/greeting",
    "commands": ["greet"],
    "permissions": ["telegram.message"],
    "min_reze_version": "2.0.0",
}

@router.register(
    name="greet",
    category="Plugins",
    description="Send a themed greeting.",
    usage=".greet [name]",
    cooldown=2,
)
async def greet(ctx: CommandContext):
    who = ctx.args_text or "there"
    return await ctx.reply(ascii.success("Hello", [f"Greetings, {who}."]))
```

`.plugintemplate` prints the same scaffold from inside Telegram.

## 2. Manifest fields

| Field | Required | Notes |
| --- | --- | --- |
| `name` | yes | Human-readable, 2-60 characters |
| `id` | recommended | Lowercase slug, 2-32 characters; defaults to the file name |
| `version` | yes | `1.2.3` style |
| `description` | yes | One sentence, English |
| `author` | recommended | Shown in the panel |
| `source` | external plugins | Where the code came from |
| `category` | no | Groups commands in `.help` |
| `tags` | no | Used by `.plugins <query>` |
| `commands` | yes | Must match the registered command names |
| `requires` | no | Python modules that must be importable |
| `optional_requires` | no | Used when present, never fatal |
| `permissions` | yes if used | Declared capabilities |
| `min_reze_version` | no | Defaults to `2.0.0` |
| `config` | no | Declarative settings schema |

Validation failures are reported with the offending field, e.g.
`Invalid plugin manifest - permissions: unknown capability: root`.

## 3. Declaring permissions

Use only what you need:

| Capability | Meaning |
| --- | --- |
| `telegram.message` | send/edit messages |
| `telegram.media` | read replied-to media |
| `telegram.account` | read account/chat metadata |
| `filesystem.read` / `filesystem.write` | files under the data directory |
| `network` | outbound HTTP |
| `ai.provider` | call the configured AI gateway |
| `process.exec` | start local processes (FFmpeg) |
| `config.read` | read non-secret configuration |
| `config.secrets` | secrets — reported as a warning, never granted as a guarantee |

These declarations are shown to the user. They are **not enforced** at runtime:
Python code in-process can bypass them. Do not rely on them for isolation, and
do not claim they provide any.

## 4. Settings

```python
MANIFEST["config"] = {
    "greeting": {"type": "string", "default": "Hello", "description": "Text sent by .greet"},
    "limit": {"type": "int", "default": 3},
    "mode": {"type": "choice", "choices": ["fast", "safe"], "default": "fast"},
    "token": {"type": "secret", "default": ""},
}

from reze.plugin_manager import PluginSettings
settings = PluginSettings("greeting", MANIFEST["config"])
settings.get("greeting")   # typed value, default when unset
settings.set("limit", 5)   # raises ValueError on invalid input
```

Values live in the `global_settings` table under `plugin:<id>:<key>` and are
editable from the panel. Secret values are masked when displayed.

## 5. Lifecycle

1. Reze scans `reze/plugins/*.py` (alphabetical, files starting with `_` are
   ignored).
2. The module is executed; its `@router.register` calls run immediately.
3. The manifest is validated, dependencies checked, and the commands it
   registered are attributed to it.
4. Failures are isolated: the plugin is marked `failed` with a reason, its
   commands are rolled back, and the rest of the userbot keeps running.
5. A command name that is already registered causes the plugin to be rejected
   (duplicate-command detection).
6. `.plugin disable <id>` unregisters the commands and persists the state;
   `.plugin enable <id>` loads it again.

Unloading cannot force already-running work started by the plugin to stop.

## 6. Compatibility policy

- `min_reze_version` is enforced on load; a newer major/minor blocks the plugin.
- Reze 2.x preserves the public router API (`register`, `CommandContext`),
  `PluginSettings` and the manifest schema. New *optional* fields may be added.
- Command names and aliases are never silently reused by core code; collisions
  are reported.
- Deprecations are listed in `CHANGELOG.md` before removal.

## 7. Testing your plugin

```python
# tests/test_greeting.py
import support  # test fixtures from this repository
from reze.plugin_manager import PluginManager

def test_loads():
    manager = PluginManager(plugins_dir="reze/plugins")
    state = manager.load("greeting")
    assert state.status == "loaded"
    assert "greet" in state.commands
```

Use `support.make_context()` to build a `CommandContext` with a dummy client and
call your handler directly. Never require real Telegram credentials in tests.

## 8. Error handling

- Raise `MediaError`, `AIError` or `RezeException` subclasses for expected
  failures; the router renders them and logs a traceback.
- Return `await ctx.reply_usage(...)` for invalid arguments.
- Never leak secrets in an exception message; the logger masks common patterns
  but does not understand custom formats.
- Prefer the shared renderer (`ascii.success`, `ascii.error`, `ascii.frame`,
  `ascii.table`) so themes stay consistent.

## 9. Installing third-party plugins

There is no remote registry. To install a plugin:

1. Read its code.
2. Place the file in `reze/plugins/<id>.py`.
3. Run `.plugin enable <id>` (or restart).
4. Check `.plugininfo <id>` for its declared capabilities and commands.

Reze never downloads or executes code automatically. A manifest or an allowlist
does not make code safe.
