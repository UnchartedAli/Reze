"""Writing DNA: a local, transparent statistical profile of your writing."""

from reze.command_router import CommandContext, router
from reze.features import require
from reze.personal.writing import writing_service
from reze.ui import ascii

CATEGORY = "Knowledge"


async def _blocked(ctx: CommandContext) -> bool:
    hint = require("writing_dna")
    if hint:
        await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        return True
    return False


@router.register(
    name="writing",
    category=CATEGORY,
    description="Add writing samples, view your profile or compare new text.",
    usage=".writing [add <text>|profile|check <text>|samples]",
    owner_only=True,
    examples=[".writing add <text or reply>", ".writing profile", ".writing check <text>"],
)
async def writing_cmd(ctx: CommandContext):
    if await _blocked(ctx):
        return
    action = (ctx.args[0].lower() if ctx.args else "profile")

    if action == "add":
        reply = await ctx.get_reply_message()
        text = " ".join(ctx.args[1:]).strip() or (getattr(reply, "message", "") or "")
        if not text:
            return await ctx.reply_usage("Reply to a message or pass text after 'add'.")
        try:
            sample_id = writing_service.add_sample(text, source="command")
        except ValueError as exc:
            return await ctx.reply(ascii.warning("Sample rejected", [str(exc)]))
        return await ctx.reply(
            ascii.success("Writing sample saved", [f"ID: {sample_id}", f"Chars: {len(text)}"])
        )

    if action == "profile":
        profile = writing_service.profile()
        if not profile.get("samples"):
            return await ctx.reply(
                ascii.info("No samples yet", ["Add one: .writing add <text>"])
            )
        metrics = profile.get("metrics") or {}
        lines = [
            f"Samples: {profile['samples']}",
            f"Average sentence: {metrics.get('avg_sentence_words', 0)} words",
            f"Average word: {metrics.get('avg_word_length', 0)} characters",
            f"Questions per sentence: {metrics.get('question_ratio', 0)}",
            f"Exclamations per sentence: {metrics.get('exclamation_ratio', 0)}",
            f"Persian characters: {round(float(metrics.get('persian_ratio', 0)) * 100, 1)}%",
            "Frequent words: " + ", ".join(word for word, _count in profile.get("top_words") or []),
        ]
        return await ctx.reply(ascii.section("Writing DNA", lines))

    if action == "check":
        text = " ".join(ctx.args[1:]).strip()
        if not text:
            return await ctx.reply_usage("Example: .writing check This is a new draft sentence.")
        result = writing_service.analyze(text)
        deviations = result.get("deviations") or {}
        lines = [
            f"Similarity: {result['similarity']}/100",
            f"Words: {(result.get('metrics') or {}).get('words', 0)}",
            f"Sentence length deviation: {deviations.get('avg_sentence_words', 0)}",
            f"Brand-new text always scores approximately; this is a statistical hint, not a verdict.",
        ]
        if not (result.get("profile") or {}).get("samples"):
            lines.append("Add samples first so the profile is meaningful.")
        return await ctx.reply(ascii.section("Writing check", lines))

    if action == "samples":
        rows = writing_service.samples(limit=20)
        if not rows:
            return await ctx.reply(ascii.info("No samples", ["Add one: .writing add <text>"]))
        lines = [f"#{row['id']} [{row['source']}] {row['content'][:60]}" for row in rows]
        return await ctx.reply(ascii.section("Writing samples", lines))

    return await ctx.reply_usage("Subcommands: add, profile, check, samples.")
