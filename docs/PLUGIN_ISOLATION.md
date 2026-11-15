# Isolated plugins

Developer: **UnchartedAli** · Channel: **[@yamods](https://t.me/yamods)**

Plugins are normally loaded into the bot's own process. A plugin loaded that way has
the bot's full access: its database, its settings, its Telegram session. The
`permissions` list in the manifest only labels what the plugin says it needs. It does
not restrict anything.

An **isolated plugin** runs in its own process, with much less access. Use isolation
for plugins you did not write, or for any plugin you want to limit.

## What isolation gives you

* **Separate process.** The plugin runs as a child Python process started with `-I -S`,
  so the bot's objects, connection and memory are not reachable from it.
* **Clean environment.** The child gets only `PATH` and a few system variables. No
  `REZE_*` settings, no tokens, no session strings.
* **Standard library only.** The worker imports nothing from REZE. The plugin can use
  `reze_sdk` (provided by the worker) and the standard library.
* **One capability: reply.** `ctx.reply(text)` sends a message, and only if the plugin
  declares `telegram.message`. Any other request is refused. The plugin's command
  arguments and sender id are passed in; it cannot ask for more.
* **Limits.** Each call has a timeout (default 5 seconds). Output is clipped to
  3,000 characters. At most five replies per call. On POSIX systems the child is limited
  to 512 MB of address space and 20 seconds of CPU time.
* **Containment.** A plugin exception is reported as an error and the process keeps
  running. A hang or a crash stops only that plugin. The bot keeps running. After five
  restarts, the plugin stays stopped until it is reloaded.
* **Approval by hash.** The first load records the SHA-256 of the file. If the file
  changes later, loading is refused until the owner approves the new version. A plugin
  that fails validation is not approved.
* **Strict manifest.** Commands the worker registers must match the manifest, both ways.

## What isolation does NOT give you

* **It is not a sandbox against hostile code.** The worker runs as the same operating
  system user as the bot. It can open any file that user can read, including the
  database file and `.env` if they are readable by that user. Isolation limits accidental
  and casual access. It does not stop a determined attacker. Do not load code you do not
  trust.
* **Resource limits are POSIX-only.** On Windows the timeout and the process boundary
  apply, but memory and CPU limits do not.
* **No network or file restrictions.** The worker is not confined by the operating
  system. Network access and file access are not blocked.
* **Only `reply` is offered.** Anything else (storing data, reading settings, calling
  Telegram) needs its own permission and host code. None of that exists yet.
* **Existing in-process plugins are unchanged.** The current loader still runs plugins in
  the bot's process. Only plugins loaded through `IsolatedPluginHost` are isolated.

## Writing an isolated plugin

Start from `docs/examples/isolated_plugin_example.py`:

```python
from reze_sdk import command

MANIFEST = {
    "id": "word_count",
    "name": "Word count",
    "description": "Counts the words you send after the command.",
    "version": "1.0.0",
    "permissions": ["telegram.message"],
    "commands": ["words"],
}

@command("words", description="Count words", usage=".words <text>")
def words(ctx):
    count = len(" ".join(ctx.args).split())
    ctx.reply(f"{count} word(s).")
    return ""
```

* Command functions are synchronous. Return a string for the final reply, or `""`.
* `ctx.args` is a list of strings, `ctx.text` is the whole message, and `ctx.sender_id`
  is the sender's id.
* A `ctx.reply()` call that the host refuses raises `HostDenied` inside the plugin.

## Loading one (code, not chat)

```python
from reze.sandbox.isolation import IsolatedPluginHost, Limits

host = IsolatedPluginHost(Limits(call_timeout=5.0))
await host.load("word_count", "path/to/word_count.py")   # registers the commands
await host.unload("word_count")                          # stops the process, removes the commands
host.approve("word_count", "path/to/word_count.py")      # after you review a changed file
```

Commands registered this way behave like other commands: `.words` and the router's
permission and cooldown checks apply.

## Loading from chat (owner only)

Feature `isolated_plugins` is OFF by default. Turn it on with `.features enable isolated_plugins confirm`.

1. Put the plugin file in `<data_dir>/isolated_plugins/` (for example `word_count.py`). Only the owner
   with access to the server can place files there. Chat cannot upload code.
2. `.isolated list` shows each file and its status: `not approved`, `approved`, `changed` or `loaded`.
3. Review the file on disk, then `.isolated approve word_count`.
4. `.isolated load word_count` starts it in its own process and registers its commands.
5. `.isolated unload word_count` stops it and removes its commands.

Chat takes a name only. The name must match `[a-z][a-z0-9_]{0,31}`. The file is resolved inside
the folder, and a symlink that points elsewhere is refused. A changed file must be approved again.
Loaded plugins are not restarted automatically after a restart of the bot. Load them again.

## Where the code lives

| Part | File |
| --- | --- |
| Worker (standard library only) | `reze/sandbox/worker.py` |
| Host: processes, limits, permissions, approval | `reze/sandbox/isolation.py` |
| Example plugin | `docs/examples/isolated_plugin_example.py` |
| Tests (start real processes) | `tests/test_reze4_plugin_isolation.py` |
