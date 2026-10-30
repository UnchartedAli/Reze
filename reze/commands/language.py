"""Language selection (English / Persian) with optional Jalali dates."""

from datetime import datetime

from reze.command_router import CommandContext, router
from reze.localization import LANGUAGES, format_date, get_language, is_rtl, set_language
from reze.localization.manager import LanguageError
from reze.ui import ascii

CATEGORY = "Settings"


@router.register(
    name="language",
    category=CATEGORY,
    description="Show or change the interface language (en / fa).",
    usage=".language [en|fa]",
    aliases=["lang"],
    owner_only=True,
    examples=[".language", ".language fa", ".language en"],
)
async def language_cmd(ctx: CommandContext):
    if not ctx.args:
        current = get_language()
        today = datetime.utcnow()
        lines = [
            f"Current: {current} ({LANGUAGES.get(current, current)})",
            f"Direction: {'right-to-left' if is_rtl(current) else 'left-to-right'}",
            f"Today (UTC): {today.strftime('%Y-%m-%d')}",
            f"Local date: {format_date(today, current)}",
            "",
            "Options: " + ", ".join(f"{code} ({name})" for code, name in LANGUAGES.items()),
            "Change with: .language fa",
        ]
        return await ctx.reply(ascii.section("Language", lines))

    requested = ctx.args[0]
    try:
        code = set_language(requested)
    except LanguageError as exc:
        return await ctx.reply(
            ascii.warning("Unsupported language", [str(exc), "Supported: en, fa"])
        )
    name = LANGUAGES.get(code, code)
    note = "Persian input is normalized automatically; dates can be shown in the Jalali calendar."
    if is_rtl(code):
        note = "\u200f" + note
    return await ctx.reply(
        ascii.success("Language updated", [f"Language: {name} ({code})", note])
    )
