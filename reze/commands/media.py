"""
REZE Studio commands: images, stickers, video and audio.

Every command follows the same pipeline: validate the reply, download the media
inside a temporary workspace, run the real conversion in a bounded background
task, send the produced file, and clean the workspace in a ``finally`` block.
Optional tools (Pillow, FFmpeg, a background-removal provider) are detected
before work starts and reported honestly when missing.
"""

import asyncio
import os

from reze.command_router import CommandContext, router
from reze.config import settings
from reze.core.confirmations import confirmations
from reze.core.tasks import TaskQueueFull, TaskStatus, task_manager
from reze.exceptions import MediaError, MissingDependencyError
from reze.logging_config import logger
from reze.media import ffmpeg, images
from reze.media.stickers import create_sticker_set, generate_short_name, add_sticker_to_set
from reze.media.workspace import MediaWorkspace, download_reply_media
from reze.ui import ascii

MEDIA_CATEGORY = "Media"


# --------------------------------------------------------------------- helpers
def _size_label(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return "unknown size"
    if size >= 1024 * 1024:
        return f"{size / 1048576:.2f} MB"
    return f"{max(1, size // 1024)} KB"


async def _run_job(
    ctx: CommandContext,
    kind: str,
    worker,
    *,
    title: str,
    caption: str = "",
    document: bool = False,
) -> None:
    """
    Download replied media, run *worker* in the task manager, send the result.

    ``worker(source_path, workspace, record)`` returns the output path.
    """
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to a media message first.")

    workspace = MediaWorkspace(kind)
    note = None
    try:
        async def factory(record):
            record.update(5, "downloading")
            source = await download_reply_media(ctx, workspace)
            record.update(20, "downloaded")
            output = worker(source, workspace, record)
            if asyncio.iscoroutine(output):
                output = await output
            return output

        try:
            task = await task_manager.submit(kind, factory, command=ctx.command_name)
        except TaskQueueFull as exc:
            return await ctx.reply(ascii.warning("Queue is full", [str(exc)]))

        note = await ctx.reply(
            ascii.loading(
                f"{title} started",
                [f"Task {ascii.code(task.id)}", "The result will follow in this chat."],
            )
        )

        try:
            record = await task_manager.wait(
                task.id, timeout=settings.task_timeout_seconds + 15
            )
        except asyncio.TimeoutError:
            await task_manager.cancel(task.id)
            return await ctx.reply(
                ascii.error("Task timed out", ["The operation took too long and was cancelled."])
            )

        if record.status != TaskStatus.COMPLETED:
            await _safe_edit(note, ascii.error(f"{title} failed", [record.error or "Unknown error."]))
            return None

        output = record.value
        if not isinstance(output, str) or not os.path.isfile(output):
            await _safe_edit(note, ascii.error(f"{title} failed", ["No output file was produced."]))
            return None

        await _safe_edit(
            note,
            ascii.success(
                f"{title} ready",
                [f"Output: {_size_label(output)}", f"Elapsed: {record.elapsed:.1f}s"],
            ),
        )
        try:
            await ctx.send_file(
                file=output,
                caption=ascii.escape_for_caption(caption) if caption else None,
                force_document=document,
            )
        except Exception as exc:  # noqa: BLE001 - Telegram send failures
            logger.error("Could not send the media result: %s", exc)
            return await ctx.reply(
                ascii.error("Upload failed", [ascii.sanitize(str(exc))[:200]])
            )
        return None
    except (MediaError, MissingDependencyError) as exc:
        if note is not None:
            return await _safe_edit(note, ascii.error(f"{title} failed", [str(exc)]))
        return await ctx.reply(ascii.error(f"{title} failed", [str(exc)]))
    except Exception as exc:  # noqa: BLE001
        logger.error("Media job failed: %s", exc, exc_info=True)
        if note is not None:
            return await _safe_edit(note, ascii.error(f"{title} failed", [ascii.sanitize(str(exc))[:200]]))
        return await ctx.reply(ascii.error(f"{title} failed", ["An unexpected error occurred."]))
    finally:
        workspace.cleanup()


async def _safe_edit(message, text: str) -> None:
    if message is None:
        return
    try:
        await message.edit(text)
    except Exception as exc:
        logger.debug("Could not update the progress message: %s", exc)


def _parse_int(value: str, label: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise MediaError(f"{label} must be a whole number.") from exc
    if not minimum <= number <= maximum:
        raise MediaError(f"{label} must be between {minimum} and {maximum}.")
    return number


def _require_ffmpeg_or_error():
    if not ffmpeg.available():
        raise MissingDependencyError(
            "FFmpeg is not installed. Install it and restart Reze "
            "(Windows: `winget install Gyan.FFmpeg`, Debian/Ubuntu: `apt install ffmpeg`)."
        )


# ---------------------------------------------------------------------- images
@router.register(
    name="sticker",
    category=MEDIA_CATEGORY,
    description="Convert a replied image into a 512x512 Telegram static sticker.",
    usage=".sticker (reply to an image)",
    cooldown=2,
)
async def sticker_cmd(ctx: CommandContext):
    def worker(source, workspace, record):
        if not images.available():
            raise MissingDependencyError("Pillow is required for stickers. Install it with pip.")
        record.update(40, "converting to WebP")
        output = workspace.child("sticker.webp")
        images.make_sticker(source, output)
        record.update(90, "validating")
        return output

    return await _run_job(
        ctx,
        "sticker",
        worker,
        title="Sticker conversion",
        caption="512x512 WebP sticker",
        document=True,
    )


@router.register(
    name="stickerpack",
    category=MEDIA_CATEGORY,
    description="Create a real Telegram sticker set from a replied image.",
    usage=".stickerpack <title> | <emoji>  then  .stickerpack confirm <code>",
    cooldown=5,
)
async def stickerpack_cmd(ctx: CommandContext):
    args = ctx.args
    if args and args[0].lower() == "confirm":
        return await _confirm_stickerpack(ctx, args[1] if len(args) > 1 else "")

    if not args:
        return await ctx.reply(
            ascii.frame(
                "Create a sticker set",
                [
                    "Reply to an image with:",
                    ".stickerpack <title> | <emoji>",
                    "Example: .stickerpack Reze Pack | 🙂",
                    "",
                    "Telegram creates the pack on your account; a confirmation code is required.",
                ],
            )
        )
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to an image and add the pack title.")

    raw = ctx.args_text
    if "|" in raw:
        title, emoji = [part.strip() for part in raw.split("|", 1)]
    else:
        title, emoji = raw.strip(), "🙂"
    title = title[:64]
    if not title:
        return await ctx.reply_usage("A sticker set title is required.")

    token = confirmations.issue(
        "stickerpack", ctx.chat_id, ctx.sender_id, payload=f"{title}|{emoji}"
    )
    return await ctx.reply(
        ascii.warning(
            "Confirm sticker set creation",
            [
                f"Title: {title}",
                f"Emoji: {emoji}",
                "Telegram will publish this pack under your account.",
                "",
                f"Reply to the same image with: .stickerpack confirm {token}",
                "The code expires in 2 minutes and works once.",
            ],
        )
    )


async def _confirm_stickerpack(ctx: CommandContext, token: str):
    if not token:
        return await ctx.reply_usage("Example: .stickerpack confirm AB12CD34")
    try:
        confirmation = confirmations.consume(token, "stickerpack", ctx.chat_id, ctx.sender_id)
    except Exception as exc:
        return await ctx.reply(ascii.error("Confirmation rejected", [str(exc)]))
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to the same image while confirming.")

    title, _, emoji = confirmation.payload.partition("|")
    short_name = generate_short_name("reze")
    workspace = MediaWorkspace("stickerpack")
    try:
        async def factory(record):
            record.update(10, "downloading")
            source = await download_reply_media(ctx, workspace)
            record.update(35, "building sticker")
            asset = workspace.child("sticker.webp")
            images.make_sticker(source, asset)
            record.update(60, "uploading to Telegram")
            result = await create_sticker_set(
                ctx.client, title=title, short_name=short_name, sticker_path=asset, emoji=emoji or "🙂"
            )
            record.update(95, "confirmed")
            return result

        task = await task_manager.submit("stickerpack", factory, command="stickerpack")
        note = await ctx.reply(
            ascii.loading("Creating sticker set", [f"Task {ascii.code(task.id)}"])
        )
        record = await task_manager.wait(task.id, timeout=settings.task_timeout_seconds + 15)
        if record.status != TaskStatus.COMPLETED:
            return await _safe_edit(
                note, ascii.error("Sticker set failed", [record.error or "Telegram rejected the request."])
            )
        result = record.value or {}
        return await _safe_edit(
            note,
            ascii.success(
                "Sticker set created",
                [
                    f"Title: {result.get('title', title)}",
                    f"Stickers: {result.get('count', 1)}",
                    f"Link: {result.get('url', '')}",
                ],
                footer="Confirmed by Telegram",
            ),
        )
    except (MediaError, MissingDependencyError) as exc:
        return await ctx.reply(ascii.error("Sticker set failed", [str(exc)]))
    except Exception as exc:  # noqa: BLE001
        logger.error("Sticker set creation failed: %s", exc, exc_info=True)
        message = ascii.sanitize(str(exc))[:250]
        return await ctx.reply(
            ascii.error(
                "Sticker set failed",
                [message, "Telegram did not confirm the pack, so no link was reported."],
            )
        )
    finally:
        workspace.cleanup()


@router.register(
    name="addsticker",
    category=MEDIA_CATEGORY,
    description="Add a replied image as a sticker to an existing set you own.",
    usage=".addsticker <set_short_name> [emoji]",
    cooldown=3,
)
async def addsticker_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .addsticker reze_pack_ab12cd34 🙂")
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to an image first.")
    short_name = ctx.args[0]
    emoji = ctx.args[1] if len(ctx.args) > 1 else "🙂"

    workspace = MediaWorkspace("addsticker")
    try:
        async def factory(record):
            record.update(10, "downloading")
            source = await download_reply_media(ctx, workspace)
            record.update(40, "building sticker")
            asset = workspace.child("sticker.webp")
            images.make_sticker(source, asset)
            record.update(70, "uploading")
            return await add_sticker_to_set(ctx.client, short_name, asset, emoji)

        try:
            task = await task_manager.submit("addsticker", factory, command="addsticker")
        except TaskQueueFull as exc:
            return await ctx.reply(ascii.warning("Queue is full", [str(exc)]))
        record = await task_manager.wait(task.id, timeout=settings.task_timeout_seconds + 15)
        if record.status != TaskStatus.COMPLETED:
            return await ctx.reply(ascii.error("Add sticker failed", [record.error or "Unknown error."]))
        return await ctx.reply(
            ascii.success(
                "Sticker added",
                [f"Set: {short_name}", f"Link: https://t.me/addstickers/{short_name}"],
            )
        )
    except (MediaError, MissingDependencyError) as exc:
        return await ctx.reply(ascii.error("Add sticker failed", [str(exc)]))
    finally:
        workspace.cleanup()


@router.register(
    name="toimage",
    category=MEDIA_CATEGORY,
    description="Extract a still image from replied media (first frame by default).",
    usage=".toimage [frame_index]",
    cooldown=2,
)
async def toimage_cmd(ctx: CommandContext):
    index = 0
    if ctx.args:
        index = _parse_int(ctx.args[0], "Frame index", 0, 5000)

    def worker(source, workspace, record):
        record.update(40, "extracting frame")
        output = workspace.child("image.png")
        images.to_image(source, output, frame_index=index)
        return output

    return await _run_job(ctx, "toimage", worker, title="Image extraction")


@router.register(
    name="resize",
    category=MEDIA_CATEGORY,
    description="Resize a replied image (or video) with aspect-ratio handling.",
    usage=".resize <width> [height]",
    cooldown=2,
)
async def resize_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .resize 1280 (or .resize 1280 720)")
    width = _parse_int(ctx.args[0], "Width", 16, 8000)
    height = None
    if len(ctx.args) > 1:
        height = _parse_int(ctx.args[1], "Height", 16, 8000)

    video_mode = len(ctx.args) > 2 and ctx.args[2].lower() == "video"

    def worker(source, workspace, record):
        if video_mode:
            _require_ffmpeg_or_error()
            record.update(40, "scaling video")
            output = workspace.child("resized.mp4")
            ffmpeg.compress_video(source, output, crf=23, width=width)
            return output
        record.update(40, "resizing image")
        output = workspace.child("resized.png")
        images.resize(source, output, width=width, height=height)
        return output

    return await _run_job(ctx, "resize", worker, title="Resize")


@router.register(
    name="compress",
    category=MEDIA_CATEGORY,
    description="Compress a replied image or video.",
    usage=".compress [quality|crf]",
    cooldown=2,
)
async def compress_cmd(ctx: CommandContext):
    quality = settings.media_quality
    if ctx.args:
        quality = _parse_int(ctx.args[0], "Quality", 20, 100)

    def worker(source, workspace, record):
        if ffmpeg.available() and hasattr(source, "lower") and os.path.splitext(source)[1].lower() in {
            ".mp4", ".mkv", ".mov", ".webm", ".avi"
        }:
            record.update(40, "compressing video")
            output = workspace.child("compressed.mp4")
            crf = max(18, min(40, 100 - quality // 2))
            ffmpeg.compress_video(source, output, crf=crf)
            return output
        record.update(40, "compressing image")
        output = workspace.child("compressed.jpg")
        images.compress(source, output, quality=quality)
        return output

    return await _run_job(ctx, "compress", worker, title="Compression")


@router.register(
    name="meme",
    category=MEDIA_CATEGORY,
    description="Add top/bottom meme text to a replied image.",
    usage=".meme <top> | <bottom>",
    cooldown=2,
)
async def meme_cmd(ctx: CommandContext):
    text = ctx.args_text
    if not text:
        return await ctx.reply_usage("Example: .meme When the deploy | Finally works")
    if "|" in text:
        top, bottom = [part.strip() for part in text.split("|", 1)]
    else:
        top, bottom = "", text.strip()

    def worker(source, workspace, record):
        record.update(40, "drawing text")
        output = workspace.child("meme.png")
        images.make_meme(source, output, top=top, bottom=bottom)
        return output

    return await _run_job(ctx, "meme", worker, title="Meme")


@router.register(
    name="caption",
    category=MEDIA_CATEGORY,
    description="Draw text on a replied image (top, center or bottom).",
    usage=".caption <text> [top|center|bottom]",
    cooldown=2,
)
async def caption_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .caption Release 2.0 bottom")
    position = "bottom"
    words = list(ctx.args)
    if words[-1].lower() in {"top", "center", "bottom"}:
        position = words.pop().lower()
    text = " ".join(words).strip()
    if not text:
        return await ctx.reply_usage("Provide the caption text.")

    def worker(source, workspace, record):
        record.update(40, "drawing text")
        output = workspace.child("captioned.png")
        images.add_caption(source, output, text, position=position)
        return output

    return await _run_job(ctx, "caption", worker, title="Caption")


@router.register(
    name="thumbnail",
    category=MEDIA_CATEGORY,
    description="Generate a thumbnail from a replied image or video.",
    usage=".thumbnail [size]",
    cooldown=2,
)
async def thumbnail_cmd(ctx: CommandContext):
    size = 320
    if ctx.args:
        size = _parse_int(ctx.args[0], "Size", 64, 1280)

    def worker(source, workspace, record):
        record.update(40, "rendering thumbnail")
        output = workspace.child("thumbnail.jpg")
        images.thumbnail(source, output, size=size)
        return output

    return await _run_job(ctx, "thumbnail", worker, title="Thumbnail")


# ------------------------------------------------------------------ video/audio
@router.register(
    name="gif",
    category=MEDIA_CATEGORY,
    description="Convert replied video or animation into a GIF.",
    usage=".gif [fps] [width]",
    cooldown=3,
)
async def gif_cmd(ctx: CommandContext):
    _require_ffmpeg_or_error()
    fps = 12
    width = 480
    if ctx.args:
        fps = _parse_int(ctx.args[0], "FPS", 5, 30)
    if len(ctx.args) > 1:
        width = _parse_int(ctx.args[1], "Width", 80, 1280)

    def worker(source, workspace, record):
        output = workspace.child("animation.gif")
        record.update(30, "converting")
        ffmpeg.to_gif(source, output, fps=fps, width=width)
        return output

    return await _run_job(ctx, "gif", worker, title="GIF conversion")


@router.register(
    name="tovideo",
    category=MEDIA_CATEGORY,
    description="Convert replied media into an H.264 MP4 video.",
    usage=".tovideo",
    cooldown=3,
)
async def tovideo_cmd(ctx: CommandContext):
    _require_ffmpeg_or_error()

    def worker(source, workspace, record):
        output = workspace.child("video.mp4")
        record.update(30, "encoding")
        ffmpeg.to_video(source, output)
        return output

    return await _run_job(ctx, "tovideo", worker, title="Video conversion")


@router.register(
    name="toaudio",
    category=MEDIA_CATEGORY,
    description="Extract the audio track from replied video or media.",
    usage=".toaudio",
    cooldown=3,
)
async def toaudio_cmd(ctx: CommandContext):
    _require_ffmpeg_or_error()

    def worker(source, workspace, record):
        output = workspace.child("audio.mp3")
        record.update(30, "extracting audio")
        ffmpeg.to_audio(source, output)
        return output

    return await _run_job(ctx, "toaudio", worker, title="Audio extraction")


@router.register(
    name="trim",
    category=MEDIA_CATEGORY,
    description="Trim replied audio or video between two timestamps.",
    usage=".trim <start> <end>   (e.g. .trim 0:05 0:35)",
    cooldown=3,
)
async def trim_cmd(ctx: CommandContext):
    _require_ffmpeg_or_error()
    if len(ctx.args) < 2:
        return await ctx.reply_usage("Example: .trim 0:05 0:35")
    start = ffmpeg.parse_timestamp(ctx.args[0])
    end = ffmpeg.parse_timestamp(ctx.args[1])
    if end <= start:
        return await ctx.reply(ascii.error("Invalid range", ["The end must be after the start."]))

    def worker(source, workspace, record):
        record.update(30, "trimming")
        extension = os.path.splitext(source)[1].lower()
        output = workspace.child("trimmed" + (extension if extension in {".mp4", ".mkv", ".mov", ".webm", ".mp3", ".m4a", ".ogg", ".wav"} else ".mp4"))
        ffmpeg.trim(source, output, start=start, end=end)
        return output

    return await _run_job(ctx, "trim", worker, title="Trim")


@router.register(
    name="speed",
    category=MEDIA_CATEGORY,
    description="Change playback speed of replied audio or video.",
    usage=".speed <factor>   (0.25 - 4.0)",
    cooldown=3,
)
async def speed_cmd(ctx: CommandContext):
    _require_ffmpeg_or_error()
    if not ctx.args:
        return await ctx.reply_usage("Example: .speed 1.5")
    try:
        factor = float(ctx.args[0])
    except ValueError:
        return await ctx.reply(ascii.error("Invalid speed", ["Use a number between 0.25 and 4.0."]))
    if not 0.25 <= factor <= 4.0:
        return await ctx.reply(ascii.error("Invalid speed", ["Use a number between 0.25 and 4.0."]))

    def worker(source, workspace, record):
        record.update(30, "re-timing")
        extension = os.path.splitext(source)[1].lower()
        is_video = extension in {".mp4", ".mkv", ".mov", ".webm", ".avi"}
        output = workspace.child("speed" + (".mp4" if is_video else ".mp3"))
        ffmpeg.change_speed(source, output, factor, is_video=is_video)
        return output

    return await _run_job(ctx, "speed", worker, title="Speed change")


@router.register(
    name="download",
    category=MEDIA_CATEGORY,
    description="Download replied media to a file (subject to Telegram access rules).",
    usage=".download",
    cooldown=2,
)
async def download_cmd(ctx: CommandContext):
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to a media message first.")
    workspace = MediaWorkspace("download")
    try:
        path = await download_reply_media(ctx, workspace)
        await ctx.send_file(
            file=path,
            caption=ascii.escape_for_caption(os.path.basename(path)),
            force_document=True,
        )
        return None
    except (MediaError, MissingDependencyError) as exc:
        return await ctx.reply(ascii.error("Download failed", [str(exc)]))
    finally:
        workspace.cleanup()


# ------------------------------------------------------------------- background
@router.register(
    name="removebg",
    category=MEDIA_CATEGORY,
    description="Remove the background of a replied image through a configured provider.",
    usage=".removebg   then   .removebg confirm <code>",
    cooldown=5,
)
async def removebg_cmd(ctx: CommandContext):
    if ctx.args and ctx.args[0].lower() == "confirm":
        return await _confirm_removebg(ctx, ctx.args[1] if len(ctx.args) > 1 else "")

    if not settings.removebg_api_key:
        return await ctx.reply(
            ascii.warning(
                "Background removal is not configured",
                [
                    "Set REZE_REMOVEBG_API_KEY to enable it (https://www.remove.bg/api).",
                    "No local background-removal model is bundled, so the command does nothing without a provider.",
                ],
            )
        )
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to an image first.")

    token = confirmations.issue("removebg", ctx.chat_id, ctx.sender_id)
    return await ctx.reply(
        ascii.warning(
            "Send this image to remove.bg?",
            [
                "The replied image will be uploaded to the remove.bg API.",
                f"Reply with: .removebg confirm {token}",
                "The code expires in 2 minutes and works once.",
            ],
        )
    )


async def _confirm_removebg(ctx: CommandContext, token: str):
    if not token:
        return await ctx.reply_usage("Example: .removebg confirm AB12CD34")
    try:
        confirmations.consume(token, "removebg", ctx.chat_id, ctx.sender_id)
    except Exception as exc:
        return await ctx.reply(ascii.error("Confirmation rejected", [str(exc)]))
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to the image again while confirming.")

    def worker(source, workspace, record):
        record.update(40, "uploading to remove.bg")
        output = workspace.child("nobg.png")
        _remove_background(source, output, record)
        return output

    return await _run_job(ctx, "removebg", worker, title="Background removal")


def _remove_background(source: str, destination: str, record) -> None:
    """Call the configured remove.bg API (real HTTP upload, no fake result)."""
    import urllib.error
    import urllib.request
    import uuid

    key = settings.removebg_api_key
    if not key:
        raise MissingDependencyError("REZE_REMOVEBG_API_KEY is not configured.")

    boundary = "----reze" + uuid.uuid4().hex
    with open(source, "rb") as handle:
        payload = handle.read()
    filename = os.path.basename(source)
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image_file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + payload + (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="size"\r\n\r\nauto\r\n'
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.remove.bg/v1.0/removebg",
        data=body,
        method="POST",
        headers={
            "X-Api-Key": key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "image/png",
        },
    )
    record.update(70, "waiting for the provider")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        raise MediaError(f"remove.bg rejected the request ({exc.code}). {detail}".strip()) from exc
    except urllib.error.URLError as exc:
        raise MediaError(f"Could not reach remove.bg: {exc.reason}") from exc

    if len(content) < 100:
        raise MediaError("remove.bg returned an empty image.")
    with open(destination, "wb") as handle:
        handle.write(content)
