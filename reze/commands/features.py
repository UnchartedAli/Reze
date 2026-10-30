"""
Optional-feature control.

Every REZE 3.0 feature starts OFF. This command is the only place that can turn
one on, and sensitive features require an explicit ``confirm`` word. Enabling a
feature never enables another one: each key is written independently, and only
background services that advertise that exact feature are started.
"""

from reze.command_router import CommandContext, router
from reze.core.registry import registry
from reze.features import (
    FEATURES,
    FeatureConfirmationRequired,
    UnknownFeature,
    feature_spec,
    features,
)
from reze.localization import get_language
from reze.ui import ascii

CATEGORY = "System"


def _start_feature_services(key: str) -> int:
    """Start registered services for *key* only. Returns how many started."""
    import asyncio

    started = 0
    for service in registry.all():
        if getattr(service, "feature", "") != key or service.status == "running":
            continue
        try:
            asyncio.get_running_loop().create_task(service.start())
            started += 1
        except RuntimeError:
            continue
    return started


def _grouped_rows(language: str):
    groups = {}
    for row in features.snapshot(language=language):
        groups.setdefault(row["category"], []).append(row)
    return groups


@router.register(
    name="features",
    category=CATEGORY,
    description="List optional features and turn them ON or OFF (OFF by default).",
    usage=".features [list|status <key>|enable <key> [confirm]|disable <key>|reset confirm]",
    aliases=["feature", "flags"],
    owner_only=True,
    examples=[
        ".features",
        ".features status vault",
        ".features enable memory",
        ".features enable workflows confirm",
        ".features disable memory",
    ],
)
async def features_cmd(ctx: CommandContext):
    language = get_language()
    topic = (ctx.args[0].lower() if ctx.args else "list")
    rest = ctx.args[1:]

    if topic in {"list", "all", ""}:
        lines = []
        for category, rows in _grouped_rows(language).items():
            on = sum(1 for row in rows if row["enabled"])
            lines.append(f"[{category}] {on}/{len(rows)} ON")
            for row in rows:
                marker = "ON " if row["enabled"] else "OFF"
                sensitive = " *" if row["sensitive"] else ""
                lines.append(f"  [{marker}] {row['key']}{sensitive} — {row['label']}")
        summary = features.summary()
        lines.append("")
        lines.append(f"Enabled: {summary['enabled']}/{summary['total']} optional features.")
        if summary["all_off"]:
            lines.append("Everything optional is OFF (fresh-install policy).")
        lines.append("* = sensitive; enabling requires: .features enable <key> confirm")
        return await ctx.reply(ascii.section("Optional features", lines))

    if topic == "status":
        if not rest:
            return await ctx.reply_usage("Example: .features status vault")
        key = rest[0].lower()
        try:
            spec = feature_spec(key)
        except UnknownFeature as exc:
            return await ctx.reply(ascii.warning("Unknown feature", [str(exc)]))
        enabled = features.is_enabled(key)
        service_states = [
            f"{service.name}: {service.status}"
            for service in registry.all()
            if getattr(service, "feature", "") == key
        ]
        lines = [
            f"Key: {spec.key}",
            f"Category: {spec.category}",
            f"State: {'ON' if enabled else 'OFF'}",
            f"Sensitive: {'yes' if spec.sensitive else 'no'}",
            f"Description: {spec.description}",
        ]
        if service_states:
            lines.append("Background services: " + ", ".join(service_states))
        return await ctx.reply(ascii.section(spec.label, lines))

    if topic in {"enable", "on", "disable", "off"}:
        if not rest:
            return await ctx.reply_usage(f"Example: .features {topic} memory")
        key = rest[0].lower()
        try:
            spec = feature_spec(key)
        except UnknownFeature as exc:
            return await ctx.reply(ascii.warning("Unknown feature", [str(exc)]))
        if topic in {"disable", "off"}:
            features.disable(key, actor=ctx.sender_id or 0)
            return await ctx.reply(
                ascii.success(
                    "Feature disabled",
                    [f"{spec.label} ({spec.key}) is now OFF.", "No other feature was changed."],
                )
            )
        confirmed = "confirm" in {value.lower() for value in rest[1:]}
        try:
            features.enable(key, actor=ctx.sender_id or 0, confirmed=confirmed)
        except FeatureConfirmationRequired:
            return await ctx.reply(
                ascii.warning(
                    "Confirmation required",
                    [
                        f"{spec.label} is a sensitive feature.",
                        f"Run: .features enable {spec.key} confirm",
                        "This explicitly opts in; nothing else will be enabled.",
                    ],
                )
            )
        started = _start_feature_services(key)
        lines = [f"{spec.label} ({spec.key}) is now ON.", "This switch affects only this feature."]
        if started:
            lines.append(f"Started {started} background service(s) for this feature.")
        if spec.sensitive:
            lines.append("Sensitive feature: every action is audited.")
        return await ctx.reply(ascii.success("Feature enabled", lines))

    if topic == "reset":
        if "confirm" not in {value.lower() for value in rest}:
            return await ctx.reply(
                ascii.warning(
                    "Confirmation required",
                    [
                        "This turns every optional feature OFF.",
                        "Run: .features reset confirm",
                    ],
                )
            )
        changed = 0
        for spec in FEATURES:
            if features.is_enabled(spec.key):
                features.disable(spec.key, actor=ctx.sender_id or 0)
                changed += 1
        return await ctx.reply(
            ascii.success(
                "All optional features OFF",
                [f"Disabled: {changed}", "Existing settings and data were preserved."],
            )
        )

    return await ctx.reply_usage("Subcommands: list, status, enable, disable, reset.")
