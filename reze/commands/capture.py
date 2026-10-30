"""
Capture commands: Smart Inbox, Universal Search, Document and Voice intelligence.

The inbox never replies to messages. Document extraction is local. Voice
transcription is the only capture feature that sends data to a third party, and
only the audio the owner explicitly asks to transcribe.
"""

import os
import tempfile

from reze.capture import documents
from reze.capture.documents import UnsupportedDocument, document_service, pdf_available
from reze.capture.inbox import inbox_service
from reze.capture.voice import VoiceUnavailable, available as voice_available, transcribe, voice_service
from reze.command_router import CommandContext, router
from reze.features import require
from reze.search import universal
from reze.ui import ascii

CATEGORY = "Capture"


def _line(row, key: str = "text", size: int = 90) -> str:
    text = " ".join(str(row.get(key) or "").split())
    return text[:size] + ("..." if len(text) > size else "")


# ------------------------------------------------------------------------ inbox
@router.register(
    name="inbox",
    category=CATEGORY,
    description="Review locally classified incoming messages (never replies).",
    usage=".inbox [list|stats|read <id>|rules|rule add <keyword|regex> <pattern>|rule delete <id>]",
    owner_only=True,
    examples=[".inbox", ".inbox stats", ".inbox rule add keyword invoice priority=5"],
)
async def inbox_cmd(ctx: CommandContext):
    hint = require("smart_inbox")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    action = (ctx.args[0].lower() if ctx.args else "list")

    if action == "list":
        status = ctx.args[1].lower() if len(ctx.args) > 1 else "new"
        rows = inbox_service.list(status=status, limit=20)
        if not rows:
            return await ctx.reply(
                ascii.info("Inbox is empty", ["Incoming messages appear here once the feature is ON."])
            )
        lines = [
            f"#{row['id']} p{row['priority']} [{row['classification']}] "
            f"{row.get('sender_name') or row.get('sender_id') or '-'}: {_line(row, 'text', 70)}"
            for row in rows
        ]
        return await ctx.reply(ascii.section(f"Inbox · {status}", lines))

    if action == "stats":
        stats = inbox_service.stats()
        lines = [f"Unread: {stats['unread']}"]
        for row in stats["by_class"]:
            lines.append(f"{row['classification']}: {row['total']}")
        return await ctx.reply(ascii.section("Inbox stats", lines))

    if action == "read":
        if len(ctx.args) < 2 or not ctx.args[1].isdigit():
            return await ctx.reply_usage("Example: .inbox read 4")
        inbox_service.mark_read(int(ctx.args[1]))
        return await ctx.reply(ascii.success("Marked read", [f"ID: {ctx.args[1]}"]))

    if action == "rules":
        rows = inbox_service.rules()
        if not rows:
            return await ctx.reply(
                ascii.info("No rules", ["Add one: .inbox rule add keyword invoice priority=5"])
            )
        lines = [
            f"#{row['id']} [{row['kind']}] {row['pattern']} -> {row['action']}={row['value']}"
            f" ({'on' if row.get('enabled') else 'off'})"
            for row in rows
        ]
        return await ctx.reply(ascii.section("Inbox rules", lines))

    if action == "rule":
        if len(ctx.args) < 4:
            return await ctx.reply_usage(
                "Example: .inbox rule add keyword invoice priority=5"
            )
        verb = ctx.args[1].lower()
        if verb == "delete":
            if not ctx.args[2].isdigit():
                return await ctx.reply_usage("Example: .inbox rule delete 2")
            inbox_service.delete_rule(int(ctx.args[2]))
            return await ctx.reply(ascii.success("Rule deleted", [f"ID: {ctx.args[2]}"]))
        if verb != "add":
            return await ctx.reply_usage("Use 'add' or 'delete'.")
        kind = ctx.args[2].lower()
        pattern = ctx.args[3]
        action_name = "priority"
        value = "4"
        for token in ctx.args[4:]:
            if "=" in token:
                key, _, raw = token.partition("=")
                if key.lower() in {"priority", "classify"}:
                    action_name, value = key.lower(), raw
        try:
            rule_id = inbox_service.add_rule(kind, pattern, action_name, value)
        except ValueError as exc:
            return await ctx.reply(ascii.warning("Invalid rule", [str(exc)]))
        return await ctx.reply(
            ascii.success("Rule saved", [f"ID: {rule_id}", f"{kind}: {pattern}"])
        )

    return await ctx.reply_usage("Subcommands: list, stats, read, rules, rule.")


# ----------------------------------------------------------------- universal search
@router.register(
    name="usearch",
    category=CATEGORY,
    description="Search memories, contacts, decisions, tasks, documents and the timeline.",
    usage=".usearch <query> [kind]",
    owner_only=True,
    examples=[".usearch invoice", ".usearch Sara contact", ".usearch roadmap task"],
)
async def usearch_cmd(ctx: CommandContext):
    hint = require("universal_search")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    if not ctx.args:
        stats = universal.stats()
        lines = [f"Indexed records: {stats['total']}", f"Engine: {'FTS5' if stats['fts5'] else 'LIKE (FTS5 unavailable)'}"]
        for row in stats["kinds"]:
            lines.append(f"{row['kind']}: {row['count']}")
        lines.append("")
        lines.append("Kinds: " + ", ".join(universal.INDEX_KINDS))
        return await ctx.reply(ascii.section("Universal search", lines))

    args = list(ctx.args)
    kind = ""
    if len(args) > 1 and args[-1].lower() in universal.INDEX_KINDS:
        kind = args.pop().lower()
    query = " ".join(args).strip()
    rows = universal.search(query, kinds=[kind] if kind else None, limit=15)
    if not rows:
        return await ctx.reply(ascii.info("No matches", [f"Nothing indexed matches '{query}'."]))
    lines = [f"[{row['kind']}] #{row['ref_id']} {_line(row, 'title', 70)}" for row in rows]
    return await ctx.reply(ascii.section(f"Search: {query}", lines))


# --------------------------------------------------------------------- documents
@router.register(
    name="doc",
    category=CATEGORY,
    description="Extract text from a replied document and index it locally.",
    usage=".doc [list|search <q>|delete <id>|status] (or reply to a file with .doc)",
    aliases=["document"],
    owner_only=True,
    examples=[".doc (as a reply to a DOCX)", ".doc list", ".doc search budget"],
)
async def doc_cmd(ctx: CommandContext):
    hint = require("document_intelligence")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    action = (ctx.args[0].lower() if ctx.args else "save")

    if action == "status":
        return await ctx.reply(
            ascii.section(
                "Document intelligence",
                [
                    f"PDF extraction: {'available' if pdf_available() else 'unavailable (install pypdf)'}",
                    "DOCX, HTML, text, Markdown, CSV and JSON: available",
                    f"Indexed documents: {document_service.count()}",
                ],
            )
        )

    if action == "list":
        rows = document_service.list(limit=20)
        if not rows:
            return await ctx.reply(ascii.info("No documents", ["Reply to a file with .doc to add one."]))
        lines = [
            f"#{row['id']} [{row['kind']}] {row['name']} — {row['chars']} chars" for row in rows
        ]
        return await ctx.reply(ascii.section("Documents", lines))

    if action == "search":
        query = " ".join(ctx.args[1:]).strip()
        if not query:
            return await ctx.reply_usage("Example: .doc search budget")
        rows = universal.search(query, kinds=["document"], limit=10)
        if not rows:
            return await ctx.reply(ascii.info("No matches", [f"No document matches '{query}'."]))
        lines = [f"#{row['ref_id']} {_line(row, 'title', 70)}" for row in rows]
        return await ctx.reply(ascii.section(f"Documents: {query}", lines))

    if action == "delete":
        if len(ctx.args) < 2 or not ctx.args[1].isdigit():
            return await ctx.reply_usage("Example: .doc delete 3")
        document_service.delete(int(ctx.args[1]))
        return await ctx.reply(ascii.success("Document deleted", [f"ID: {ctx.args[1]}"]))

    if action not in {"save", "add"}:
        return await ctx.reply_usage("Subcommands: list, search, delete, status (or reply to a file).")

    reply = await ctx.get_reply_message()
    if reply is None or not getattr(reply, "media", None):
        return await ctx.reply_usage("Reply to a document with .doc, or use .doc list.")
    name = _document_name(reply)
    try:
        payload = await reply.download_media(file=bytes)
    except Exception as exc:  # noqa: BLE001 - download failures are user-visible
        return await ctx.reply(ascii.warning("Download failed", [ascii.sanitize(str(exc))[:200]]))
    if not payload:
        return await ctx.reply(ascii.warning("No file", ["Telegram did not return the document."]))
    try:
        kind, text = documents.extract(name, payload)
    except UnsupportedDocument as exc:
        return await ctx.reply(ascii.warning("Unsupported", [str(exc)]))
    try:
        document_id = document_service.store(name, text, source="telegram", kind=kind)
    except ValueError as exc:
        return await ctx.reply(ascii.warning("Nothing to store", [str(exc)]))
    return await ctx.reply(
        ascii.success(
            "Document stored",
            [
                f"ID: {document_id}",
                f"Type: {kind}",
                f"Extracted: {len(text)} characters",
                "Search it with: .doc search <words>",
            ],
        )
    )


def _document_name(reply) -> str:
    document = getattr(reply, "document", None)
    name = ""
    for attribute in getattr(document, "attributes", []) or []:
        candidate = getattr(attribute, "file_name", "")
        if candidate:
            name = candidate
            break
    if not name:
        voice = getattr(reply, "voice", None)
        audio = getattr(reply, "audio", None)
        if voice is not None:
            name = "voice.ogg"
        elif audio is not None:
            name = getattr(audio, "title", "") or "audio.ogg"
        else:
            name = "document.bin"
    return name


# ------------------------------------------------------------------------- voice
@router.register(
    name="voice",
    category=CATEGORY,
    description="Transcribe a replied voice note through the configured AI provider.",
    usage=".voice (as a reply to a voice message)",
    aliases=["transcribe"],
    owner_only=True,
    cooldown=30,
    examples=[".voice (as a reply to a voice note)", ".voice list"],
)
async def voice_cmd(ctx: CommandContext):
    hint = require("voice_intelligence")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))

    if ctx.args and ctx.args[0].lower() in {"list", "recent"}:
        rows = voice_service.recent(limit=10)
        if not rows:
            return await ctx.reply(ascii.info("No transcripts", ["Reply to a voice note with .voice."]))
        lines = [
            f"#{row['id']} {row['duration_seconds']}s · {row['created_at']} · chat {row['chat_id']}"
            for row in rows
        ]
        return await ctx.reply(ascii.section("Voice notes", lines))

    if not voice_available():
        return await ctx.reply(
            ascii.warning(
                "Transcription unavailable",
                [
                    "Voice intelligence needs an OpenAI-compatible API key.",
                    "Set REZE_AI_API_KEY (and optionally REZE_AI_BASE_URL, REZE_VOICE_MODEL).",
                ],
            )
        )
    reply = await ctx.get_reply_message()
    if reply is None or not (getattr(reply, "voice", None) or getattr(reply, "audio", None)):
        return await ctx.reply_usage("Reply to a voice message with .voice.")
    directory = tempfile.mkdtemp(prefix="reze-voice-")
    path = os.path.join(directory, "audio.ogg")
    try:
        downloaded = await reply.download_media(file=path)
        if not downloaded or not os.path.isfile(path):
            return await ctx.reply(ascii.warning("Download failed", ["The voice file was not received."]))
        transcript = await transcribe(path)
    except VoiceUnavailable as exc:
        return await ctx.reply(ascii.warning("Transcription failed", [str(exc)]))
    finally:
        try:
            os.remove(path)
            os.rmdir(directory)
        except OSError:
            pass
    duration = 0
    voice = getattr(reply, "voice", None)
    if voice is not None:
        duration = int(getattr(voice, "duration", 0) or 0)
    voice_id = voice_service.store(
        transcript,
        duration_seconds=duration,
        chat_id=ctx.chat_id or 0,
        message_id=getattr(reply, "id", 0) or 0,
    )
    return await ctx.reply(
        ascii.success(
            "Transcript",
            [transcript, "", f"Stored as voice note #{voice_id}"],
            footer="The audio was sent only to your configured provider",
        )
    )
