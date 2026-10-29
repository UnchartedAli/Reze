"""
Downloader commands.

    .yt / .play <query|link>   video (<=720p)        .ytv [360|480|720|1080] <q|link>
    .yta <query|link>          audio as mp3          .song <query>   audio with title/artist
    .instagram / .ig <link>    .tiktok / .tt <link>  .facebook / .fb <link>
    .pinterest <link>          .mediafire <link>

These commands download from third-party sites for *your own* use: respect the
copyright and terms of service of what you download. Needs yt-dlp (and FFmpeg
for audio/merging); Pinterest and MediaFire need nothing extra.
"""

import asyncio
import os
from typing import Awaitable, Callable, Optional

from reze.command_router import CommandContext, router
from reze.config import settings
from reze.core import http
from reze.exceptions import MediaError, MissingDependencyError
from reze.logging_config import logger
from reze.media import downloaders as dl
from reze.media.downloaders import Fetched
from reze.media.workspace import MediaWorkspace
from reze.ui import ascii

CATEGORY = "Download"
MAX_SECONDS = 3600


def _cookies() -> Optional[str]:
    return os.environ.get("REZE_YTDLP_COOKIES") or None


def _limit_mb() -> int:
    return int(settings.media_max_output_mb)


async def _fetch_ytdlp(workspace: MediaWorkspace, target: str, mode: str, quality: int = 720) -> Fetched:
    return await asyncio.to_thread(
        dl.ytdlp_fetch, target, workspace.directory,
        mode=mode, quality=quality, max_mb=_limit_mb(), max_seconds=MAX_SECONDS, cookies=_cookies(),
    )


def _caption(fetched: Fetched) -> str:
    parts = [fetched.title, fetched.uploader]
    text = " - ".join(p for p in parts if p)
    if fetched.duration:
        minutes, seconds = divmod(fetched.duration, 60)
        text += f"  [{minutes}:{seconds:02d}]"
    return ascii.escape_for_caption(text[:200]) if text else ""


def _attributes(fetched: Fetched):
    from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

    if fetched.kind == "audio":
        return [DocumentAttributeAudio(duration=fetched.duration, title=fetched.title or None,
                                       performer=fetched.uploader or None)]
    if fetched.kind == "video" and fetched.width and fetched.height:
        return [DocumentAttributeVideo(duration=fetched.duration, w=fetched.width, h=fetched.height,
                                       supports_streaming=True)]
    return []


async def _run(ctx: CommandContext, title: str, produce: Callable[[MediaWorkspace], Awaitable[Fetched]]):
    workspace = MediaWorkspace("dl")
    note = await ctx.reply(ascii.loading(f"{title} started", ["Fetching, this can take a minute."]))
    try:
        fetched = await asyncio.wait_for(produce(workspace), timeout=settings.task_timeout_seconds)
        size = os.path.getsize(fetched.path)
        if size > _limit_mb() * 1024 * 1024:
            raise MediaError(f"The result is {size / 1048576:.1f} MB; the limit is {_limit_mb()} MB.")

        kwargs = {"file": fetched.path, "caption": _caption(fetched) or None}
        if fetched.kind in ("audio", "video"):
            kwargs["attributes"] = _attributes(fetched)
            kwargs["supports_streaming"] = fetched.kind == "video"
        elif fetched.kind == "file":
            kwargs["force_document"] = True
        await ctx.send_file(**kwargs)
        await _discard(note)
        return None
    except asyncio.TimeoutError:
        return await _fail(note, ctx, title, "The download took too long and was cancelled.")
    except (MediaError, MissingDependencyError, http.HttpError) as exc:
        return await _fail(note, ctx, title, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("%s failed: %s", title, exc, exc_info=True)
        return await _fail(note, ctx, title, ascii.sanitize(str(exc))[:160] or "Unexpected error.")
    finally:
        workspace.cleanup()


async def _discard(note) -> None:
    try:
        if note is not None:
            await note.delete()
    except Exception:  # noqa: BLE001
        pass


async def _fail(note, ctx, title, detail):
    text = ascii.error(f"{title} failed", [detail])
    try:
        if note is not None:
            return await note.edit(text)
    except Exception:  # noqa: BLE001
        pass
    return await ctx.reply(text)


def _target(ctx: CommandContext, args=None) -> str:
    text = " ".join(ctx.args if args is None else args).strip()
    return dl.extract_url(text) or text


async def _need_target(ctx: CommandContext, target: str, example: str):
    if not target:
        await ctx.reply_usage(example)
        return False
    return True


# -------------------------------------------------------------------------- YouTube
def _youtube_target(target: str) -> str:
    """A link must be a YouTube link; anything else is treated as search words."""
    if target.startswith("https://"):
        dl.require_site(target, "youtube")
    return target


@router.register(name="yt", category=CATEGORY, aliases=["play"], cooldown=8,
                 description="Download a YouTube video (<=720p) by link or search words.",
                 usage=".yt <link | search words>", examples=[".yt lofi hip hop"])
async def yt_cmd(ctx: CommandContext):
    target = _target(ctx)
    if not await _need_target(ctx, target, "Example: .yt lofi hip hop"):
        return None
    try:
        target = _youtube_target(target)
    except MediaError as exc:
        return await ctx.reply(ascii.error("YouTube", [str(exc)]))
    return await _run(ctx, "YouTube video", lambda ws: _fetch_ytdlp(ws, target, "video", 720))


@router.register(name="ytv", category=CATEGORY, cooldown=8,
                 description="Download a YouTube video in a chosen quality.",
                 usage=".ytv [144|240|360|480|720|1080] <link | search words>")
async def ytv_cmd(ctx: CommandContext):
    quality, rest = dl.split_quality(ctx.args)
    target = _target(ctx, rest)
    if not await _need_target(ctx, target, "Example: .ytv 360 lofi hip hop"):
        return None
    try:
        target = _youtube_target(target)
    except MediaError as exc:
        return await ctx.reply(ascii.error("YouTube", [str(exc)]))
    return await _run(ctx, f"YouTube video {quality}p", lambda ws: _fetch_ytdlp(ws, target, "video", quality))


@router.register(name="yta", category=CATEGORY, cooldown=8,
                 description="Download only the audio of a YouTube video (mp3).",
                 usage=".yta <link | search words>")
async def yta_cmd(ctx: CommandContext):
    target = _target(ctx)
    if not await _need_target(ctx, target, "Example: .yta daft punk around the world"):
        return None
    try:
        target = _youtube_target(target)
    except MediaError as exc:
        return await ctx.reply(ascii.error("YouTube", [str(exc)]))
    return await _run(ctx, "YouTube audio", lambda ws: _fetch_ytdlp(ws, target, "audio"))


@router.register(name="song", category=CATEGORY, cooldown=8,
                 description="Search a song by name and send it as audio.",
                 usage=".song <song name>", examples=[".song Bohemian Rhapsody"])
async def song_cmd(ctx: CommandContext):
    query = ctx.args_text.strip()
    if not query:
        return await ctx.reply_usage("Example: .song Bohemian Rhapsody")
    if query.startswith("http"):
        return await ctx.reply(ascii.warning("Use .yta for links", ["`.song` searches by name."]))
    return await _run(ctx, "Song", lambda ws: _fetch_ytdlp(ws, query, "audio"))


# --------------------------------------------------------------- Instagram/TikTok/FB
def _social(name: str, site: str, aliases, description: str):
    @router.register(name=name, category=CATEGORY, aliases=aliases, cooldown=8,
                     description=description, usage=f".{name} <link>")
    async def handler(ctx: CommandContext):
        reply = await ctx.get_reply_message()
        raw = ctx.args_text or (getattr(reply, "text", "") or "")
        try:
            url = dl.require_site(dl.extract_url(raw), site)
        except MediaError as exc:
            return await ctx.reply_usage(str(exc))
        return await _run(ctx, f"{site.title()} download", lambda ws: _fetch_ytdlp(ws, url, "video", 720))

    handler.__name__ = f"{name}_cmd"
    return handler


instagram_cmd = _social("instagram", "instagram", ["ig"], "Download an Instagram post or reel (video).")
tiktok_cmd = _social("tiktok", "tiktok", ["tt"], "Download a TikTok video.")
facebook_cmd = _social("facebook", "facebook", ["fb"], "Download a Facebook video.")


# ------------------------------------------------------------------------ Pinterest
async def _fetch_pinterest(workspace: MediaWorkspace, url: str) -> Fetched:
    allowed = dl.SITES["pinterest"] + dl.PINTEREST_MEDIA_HOSTS
    final, page = await http.get_text(url, allowed=allowed)
    media_url, kind = dl.pick_pinterest_media(dl.parse_og(page))
    if not media_url:
        raise MediaError("No downloadable image or video was found on that pin.")
    ext = dl.guess_extension(media_url)
    path = workspace.child(f"pin{ext}")
    await http.download(media_url, path, max_bytes=_limit_mb() * 1024 * 1024, allowed=dl.PINTEREST_MEDIA_HOSTS)
    return Fetched(path=path, kind=kind, title="Pinterest")


@router.register(name="pinterest", category=CATEGORY, cooldown=6,
                 description="Download the image or video of a Pinterest pin.", usage=".pinterest <pin link>")
async def pinterest_cmd(ctx: CommandContext):
    try:
        url = dl.require_site(dl.extract_url(ctx.args_text), "pinterest")
    except MediaError as exc:
        return await ctx.reply_usage(str(exc))
    return await _run(ctx, "Pinterest", lambda ws: _fetch_pinterest(ws, url))


# ------------------------------------------------------------------------ MediaFire
async def _fetch_mediafire(workspace: MediaWorkspace, url: str) -> Fetched:
    _, page = await http.get_text(url, allowed=dl.SITES["mediafire"])
    direct = dl.parse_mediafire(page)
    if not direct:
        raise MediaError("Could not find the download link (the file may be removed or protected).")
    name = os.path.basename(direct.split("?", 1)[0]) or "mediafire.bin"
    path = workspace.child(name)
    await http.download(direct, path, max_bytes=_limit_mb() * 1024 * 1024, allowed=dl.SITES["mediafire"])
    return Fetched(path=path, kind="file", title=name)


@router.register(name="mediafire", category=CATEGORY, cooldown=8,
                 description="Download a file from a MediaFire link.", usage=".mediafire <link>")
async def mediafire_cmd(ctx: CommandContext):
    try:
        url = dl.require_site(dl.extract_url(ctx.args_text), "mediafire")
    except MediaError as exc:
        return await ctx.reply_usage(str(exc))
    return await _run(ctx, "MediaFire", lambda ws: _fetch_mediafire(ws, url))
