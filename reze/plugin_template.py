"""Copy-paste plugin template rendered by ``.plugintemplate``."""

PLUGIN_TEMPLATE = '''"""
<Plugin display name> - a Reze plugin.

Install: drop this file into reze/plugins/<plugin_id>.py, then run
    .plugins                 # verify the manifest was accepted
    .plugin enable <plugin_id>
"""

from reze.command_router import CommandContext, router
from reze.plugin_manager import PluginSettings
from reze.ui import ascii

MANIFEST = {
    "name": "My Plugin",
    "id": "my_plugin",              # lowercase slug, 2-32 chars
    "version": "1.0.0",
    "description": "What this plugin does in one sentence.",
    "author": "your-name",
    "source": "https://example.com/my-plugin",   # required for external plugins
    "category": "Plugins",
    "tags": ["utility"],
    "commands": ["mycommand"],      # must match @router.register names
    "requires": [],                 # Python modules that must be installed
    "optional_requires": [],        # used when available, never required
    "permissions": ["telegram.message"],
    "min_reze_version": "2.0.0",
    "config": {
        "response": {
            "type": "string",
            "default": "Hello!",
            "description": "Text sent by .mycommand",
        }
    },
}

settings = PluginSettings("my_plugin", MANIFEST["config"])


@router.register(
    name="mycommand",
    category="Plugins",
    description="Say the configured response.",
    usage=".mycommand [extra text]",
    owner_only=True,
    cooldown=2,
    permissions=("telegram.message",),
    examples=[".mycommand hello"],
)
async def mycommand(ctx: CommandContext):
    extra = f" ({ctx.args_text})" if ctx.args_text else ""
    return await ctx.reply(
        ascii.success("My Plugin", [f"{settings.get('response')}{extra}"])
    )
'''
