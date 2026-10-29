"""
REZE Intelligence commands.

Every command sends content to a provider only because the user invoked it, and
every response reports which provider/model answered, how long it took and how
many tokens were used. Prompts and responses are never logged.
"""

import asyncio

from reze.ai.gateway import AIResult, ai_gateway
from reze.command_router import CommandContext, router
from reze.config import settings
from reze.exceptions import AIError, AIConfigurationError
from reze.logging_config import logger
from reze.media import images
from reze.media.workspace import MediaWorkspace, download_reply_media
from reze.ui import ascii

CATEGORY = "Intelligence"

MAX_SUMMARY_INPUT = 6000


async def _reply_text(ctx: CommandContext) -> str:
    """Text of the replied message, if any."""
    reply = await ctx.get_reply_message()
    if reply is None:
        return ""
    return getattr(reply, "message", "") or getattr(reply, "text", "") or ""


async def _collect_input(ctx: CommandContext, *, allow_args: bool = True) -> str:
    text = await _reply_text(ctx)
    if not text and allow_args:
        text = ctx.args_text
    text = (text or "").strip()
    if not text:
        raise AIError("Reply to a message with text, or pass the text as an argument.")
    return text[: settings.ai_max_input_chars]


def _render_result(result: AIResult, title: str, extra=None) -> str:
    body = [result.text] + list(extra or [])
    return ascii.frame(
        title,
        body,
        footer=result.metadata_line() + " · AI output may be inaccurate",
    )


async def _run(ctx: CommandContext, prompt: str, title: str, system: str = "", extra=None):
    try:
        result = await ai_gateway.complete(prompt, system=system)
    except AIConfigurationError as exc:
        return await ctx.reply(
            ascii.warning(
                "AI is not configured",
                [
                    str(exc),
                    "Core commands keep working without AI.",
                    "Set REZE_AI_PROVIDER, REZE_AI_MODEL and REZE_AI_API_KEY.",
                ],
            )
        )
    except AIError as exc:
        return await ctx.reply(ascii.error("AI request failed", [ascii.sanitize(str(exc))[:300]]))
    except Exception as exc:  # noqa: BLE001 - provider/network failures
        logger.error("AI command failed: %s", exc, exc_info=True)
        return await ctx.reply(
            ascii.error("AI request failed", ["The provider request could not be completed."])
        )
    return await ctx.reply(_render_result(result, title, extra))


@router.register(
    name="ai",
    category=CATEGORY,
    description="Ask the configured AI provider a question (or transform replied text).",
    usage=".ai <prompt>",
    cooldown=3,
)
async def ai_cmd(ctx: CommandContext):
    prompt = ctx.args_text.strip()
    replied = await _reply_text(ctx)
    if replied:
        prompt = f"{prompt}\n\nMessage:\n{replied[: settings.ai_max_input_chars]}".strip()
    if not prompt:
        return await ctx.reply_usage("Example: .ai Explain what MTProto session strings are")
    return await _run(ctx, prompt, "Reze Intelligence")


@router.register(
    name="summarize",
    category=CATEGORY,
    description="Summarize replied text or the provided text with the AI provider.",
    usage=".summarize [text]",
    cooldown=5,
)
async def summarize_cmd(ctx: CommandContext):
    try:
        content = await _collect_input(ctx)
    except AIError as exc:
        return await ctx.reply(ascii.warning("Nothing to summarize", [str(exc)]))
    prompt = (
        "Summarize the following content in at most 8 bullet points. "
        "Keep names, numbers and decisions. Do not add information.\n\n" + content[:MAX_SUMMARY_INPUT]
    )
    return await _run(ctx, prompt, "Summary", system="You are a precise technical summarizer.")


@router.register(
    name="translate",
    aliases=["tr"],
    category=CATEGORY,
    description="Translate replied or provided text into another language.",
    usage=".translate <language> [text]",
    cooldown=5,
)
async def translate_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .translate German (as a reply to the text)")
    language = ctx.args[0][:40]
    replied = await _reply_text(ctx)
    content = replied or " ".join(ctx.args[1:])
    if not content.strip():
        return await ctx.reply(
            ascii.warning("Nothing to translate", ["Reply to a message or pass the text."])
        )
    prompt = (
        f"Translate the following text into {language}. Preserve formatting, names and "
        f"technical terms. Return only the translation.\n\n{content[: settings.ai_max_input_chars]}"
    )
    return await _run(ctx, prompt, f"Translation → {language}")


REWRITE_STYLES = {
    "shorter": "Rewrite the text to be shorter while keeping every important fact.",
    "formal": "Rewrite the text in a formal, professional tone.",
    "casual": "Rewrite the text in a casual, friendly tone.",
    "clearer": "Rewrite the text so it is clearer and easier to read.",
    "bullets": "Rewrite the text as a concise bullet list.",
}


@router.register(
    name="rewrite",
    category=CATEGORY,
    description="Rewrite replied or provided text in a chosen style.",
    usage=".rewrite <shorter|formal|casual|clearer|bullets>",
    cooldown=5,
)
async def rewrite_cmd(ctx: CommandContext):
    style = (ctx.args[0].lower() if ctx.args else "clearer")
    if style not in REWRITE_STYLES:
        return await ctx.reply_usage("Styles: " + ", ".join(sorted(REWRITE_STYLES)))
    try:
        content = await _collect_input(ctx)
    except AIError as exc:
        return await ctx.reply(ascii.warning("Nothing to rewrite", [str(exc)]))
    prompt = f"{REWRITE_STYLES[style]}\n\n{content[:MAX_SUMMARY_INPUT]}"
    return await _run(ctx, prompt, f"Rewrite: {style}")


@router.register(
    name="digest",
    category=CATEGORY,
    description="Summarize the last few messages of this chat (bounded, explicit limit).",
    usage=".digest [count]",
    cooldown=10,
)
async def digest_cmd(ctx: CommandContext):
    count = 25
    if ctx.args:
        try:
            count = int(ctx.args[0])
        except ValueError:
            return await ctx.reply_usage("Example: .digest 30")
    count = max(5, min(count, min(settings.search_scan_limit, 60)))
    client = ctx.client
    if client is None or not hasattr(client, "iter_messages"):
        return await ctx.reply(
            ascii.warning("Digest unavailable", ["This command needs an active Telegram client."])
        )

    messages = []
    try:
        async for message in client.iter_messages(ctx.chat_id, limit=count):
            text = getattr(message, "message", "") or ""
            if text.strip():
                messages.append(text.strip())
    except Exception as exc:  # noqa: BLE001 - Telegram permission errors
        return await ctx.reply(
            ascii.error("Could not read messages", [ascii.sanitize(str(exc))[:200]])
        )

    if not messages:
        return await ctx.reply(ascii.info("Nothing to digest", ["No text messages were found."]))

    joined = "\n".join(reversed(messages))[: settings.ai_max_input_chars]
    prompt = (
        f"Summarize these {len(messages)} chat messages into at most 8 bullet points, "
        "then list open questions if any. Do not invent facts.\n\n" + joined
    )
    return await _run(
        ctx,
        prompt,
        "Chat digest",
        extra=[f"Scanned: {len(messages)} recent messages"],
    )


@router.register(
    name="describe",
    category=CATEGORY,
    description="Describe a replied image using a vision-capable model.",
    usage=".describe (reply to an image)",
    cooldown=5,
)
async def describe_cmd(ctx: CommandContext):
    status = ai_gateway.status()
    if not status["configured"]:
        return await ctx.reply(
            ascii.warning(
                "Vision is not configured",
                ["Set the AI provider, model and key first; then reply to an image with .describe."],
            )
        )
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to an image first.")
    if not images.available():
        return await ctx.reply(
            ascii.warning("Pillow is missing", ["Install Pillow to prepare images for the model."])
        )

    workspace = MediaWorkspace("describe")
    try:
        source = await download_reply_media(ctx, workspace)
        prompt = ctx.args_text or "Describe this image in detail: text, objects, layout and notable details."
        result = await ai_gateway.describe_image(source, prompt=prompt)
        return await ctx.reply(_render_result(result, "Image description"))
    except AIError as exc:
        return await ctx.reply(ascii.error("Vision request failed", [ascii.sanitize(str(exc))[:300]]))
    except Exception as exc:  # noqa: BLE001
        logger.error("Vision command failed: %s", exc, exc_info=True)
        return await ctx.reply(
            ascii.error("Vision request failed", ["The image could not be processed or described."])
        )
    finally:
        workspace.cleanup()


@router.register(
    name="aiinfo",
    category=CATEGORY,
    description="Show the configured AI provider and model without revealing secrets.",
    usage=".aiinfo",
    aliases=["ai_info"],
)
async def aiinfo_cmd(ctx: CommandContext):
    status = ai_gateway.status()
    lines = [
        f"Provider: {status['provider']}",
        f"Model: {status['model']}",
        f"Credential: {'configured' if status['api_key_present'] else 'missing'}",
        f"Vision: {'enabled' if status['vision'] else 'disabled'} (mode: {status['vision_mode']})",
        f"Timeout: {status['timeout']}s",
        f"Input limit: {status['max_input_chars']} characters",
        f"Max output: {status['max_output_tokens']} tokens",
        f"Fallback: {', '.join(status['fallbacks']) or 'none configured'}",
    ]
    if status["base_url"]:
        lines.append(f"Base URL: {status['base_url']}")
    return await ctx.reply(
        ascii.frame(
            "AI configuration",
            lines,
            footer="Secrets are never displayed",
        )
    )
