"""Example isolated plugin. Copy it, change the id and commands, then load it with IsolatedPluginHost.

It can use only the standard library and the reze_sdk module. It cannot import REZE.
Its only capability is ctx.reply(), and that needs "telegram.message" in MANIFEST.
"""

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
    ctx.reply(f"{count} word(s).")  # delivered as its own message
    return ""  # nothing more to send
