"""
Plugin management commands.

.plugins [query]        list / search installed plugins
.plugin info <name>     manifest, capabilities, commands, settings
.plugin enable <name>   enable and load
.plugin disable <name>  unload and persist the disabled state
.plugin reload <name>   reload from disk
.plugininfo <name>      alias for .plugin info
.plugintemplate         print the copy-paste plugin template
"""

from reze.command_router import CommandContext, router
from reze.plugin_manager import plugin_manager
from reze.plugin_template import PLUGIN_TEMPLATE
from reze.ui import ascii


def _permission_lines(state) -> list:
    manifest = state.manifest
    if manifest is None:
        return ["No manifest available."]
    if not manifest.permissions:
        return ["No capabilities requested."]
    from reze.plugins.manifest import CAPABILITIES

    return [f"{name} - {CAPABILITIES.get(name, 'unknown')}" for name in manifest.permissions]


@router.register(
    name="plugins",
    category="Plugins",
    description="List installed plugins with status, version and commands.",
    usage=".plugins [search]",
    owner_only=True,
)
async def plugins_cmd(ctx: CommandContext):
    query = ctx.args_text.lower()
    states = sorted(plugin_manager.states.values(), key=lambda state: state.name)
    if query:
        states = [
            state
            for state in states
            if query in state.name.lower()
            or (state.manifest is not None and query in state.manifest.description.lower())
            or (state.manifest is not None and query in " ".join(state.manifest.tags).lower())
        ]

    if not states:
        return await ctx.reply(
            ascii.info(
                "No plugins installed",
                ["Drop a plugin into reze/plugins and restart, then run .plugins."],
            )
        )

    summary = plugin_manager.status()
    rows = []
    for state in states:
        version = state.manifest.version if state.manifest else "-"
        rows.append(
            [
                state.name,
                version,
                state.status,
                ", ".join(state.commands) if state.commands else "-",
            ]
        )

    body = [
        ascii.table(["PLUGIN", "VER", "STATE", "COMMANDS"], rows),
        "",
        f"Loaded: {summary['loaded']}  Failed: {summary['failed']}  Disabled: {summary['disabled']}",
    ]
    if summary["failures"]:
        body.append("")
        body.append("Failures:")
        for name, error in summary["failures"].items():
            body.append(f"- {name}: {error[:160]}")
    body.append("")
    body.append("Inspect with .plugin info <name>")
    return await ctx.reply(ascii.section("Plugin registry", body))


@router.register(
    name="plugin",
    category="Plugins",
    description="Manage a plugin: info, enable, disable, reload.",
    usage=".plugin <info|enable|disable|reload> <name>",
    owner_only=True,
)
async def plugin_cmd(ctx: CommandContext):
    if len(ctx.args) < 2:
        return await ctx.reply_usage("Example: .plugin info example")
    action = ctx.args[0].lower()
    name = ctx.args[1].lower()

    if action == "info":
        return await _plugin_info(ctx, name)

    if action == "enable":
        try:
            state = plugin_manager.enable(name)
        except Exception as exc:
            return await ctx.reply(ascii.error("Enable failed", [str(exc)]))
        return await ctx.reply(
            ascii.success(
                "Plugin enabled",
                [f"{state.name} is loaded.", f"Commands: {', '.join(state.commands) or 'none'}"],
            )
        )

    if action == "disable":
        state = plugin_manager.get(name)
        if state is None or state.status != "loaded":
            return await ctx.reply(ascii.warning("Not loaded", [f"Plugin '{name}' is not loaded."]))
        plugin_manager.disable(name)
        return await ctx.reply(
            ascii.success(
                "Plugin disabled",
                [
                    f"{name} is disabled and its commands were unregistered.",
                    "Running work started by the plugin cannot be force-stopped.",
                ],
            )
        )

    if action == "reload":
        try:
            state = plugin_manager.reload(name)
        except Exception as exc:
            return await ctx.reply(ascii.error("Reload failed", [str(exc)]))
        return await ctx.reply(
            ascii.success("Plugin reloaded", [f"{state.name} v{state.manifest.version}"])
        )

    return await ctx.reply_usage("Actions: info, enable, disable, reload")


@router.register(
    name="plugininfo",
    category="Plugins",
    description="Show one plugin's manifest, capabilities and settings.",
    usage=".plugininfo <name>",
    owner_only=True,
    aliases=["pinfo"],
)
async def plugininfo_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .plugininfo example")
    return await _plugin_info(ctx, ctx.args[0].lower())


async def _plugin_info(ctx: CommandContext, name: str):
    state = plugin_manager.get(name)
    if state is None:
        known = ", ".join(sorted(plugin_manager.states)) or "none"
        return await ctx.reply(
            ascii.warning("Unknown plugin", [f"'{name}' is not installed.", f"Installed: {known}"])
        )

    manifest = state.manifest
    lines = [
        f"Status: {state.status}",
        f"Path: {state.path}",
    ]
    if state.error:
        lines.append(f"Error: {state.error}")
    if manifest is not None:
        lines.extend(
            [
                f"Version: {manifest.version}",
                f"Author: {manifest.author or 'unknown'}",
                f"Source: {manifest.source or 'unknown'}",
                f"Description: {manifest.description}",
                f"Minimum Reze: {manifest.min_reze_version}",
                f"Requires: {', '.join(manifest.requires) or 'nothing'}",
            ]
        )
        if manifest.config:
            settings = plugin_manager.settings_for(name)
            values = settings.public() if settings else {}
            lines.append("Settings:")
            for key, value in values.items():
                lines.append(f"  {key} = {value}")
        lines.append("Capabilities:")
        lines.extend(f"  {item}" for item in _permission_lines(state))
        for warning in state.warnings:
            lines.append(f"Note: {warning}")
        lines.append(f"Commands: {', '.join(state.commands) or 'none'}")

    return await ctx.reply(ascii.frame(f"Plugin: {name}", lines, footer="In-process plugin"))


@router.register(
    name="plugintemplate",
    category="Plugins",
    description="Print the copy-paste plugin template.",
    usage=".plugintemplate",
    owner_only=True,
)
async def plugintemplate_cmd(ctx: CommandContext):
    header = ascii.info(
        "Plugin template",
        [
            "Save as reze/plugins/<id>.py, then run .plugin reload <id>.",
            "Full guide: docs/PLUGIN_GUIDE.md",
        ],
    )
    # The template is long: the router splits it into Telegram-safe messages.
    return await ctx.reply(header + "\n\n```\n" + PLUGIN_TEMPLATE + "\n```")
