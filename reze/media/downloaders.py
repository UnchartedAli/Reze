"""
Link downloaders (YouTube, Instagram, TikTok, Facebook, Pinterest, MediaFire).

* yt-dlp does the heavy lifting for video/audio sites. It is an *optional*
  dependency: when missing, commands explain how to install it.
* Pinterest and MediaFire are handled by tiny HTML parsers (stdlib only).
* Every user-supplied URL must be https and belong to the site the command is
  for; arbitrary links are refused, so the commands cannot be used to make the
  host fetch internal addresses.

This module deliberately does not import ``reze.config``: callers pass limits in.
"""

import base64
import html as htmllib
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from reze.exceptions import MediaError, MissingDependencyError

SITES: Dict[str, List[str]] = {
    "youtube": ["youtube.com", "youtu.be", "youtube-nocookie.com"],
    "instagram": ["instagram.com"],
    "tiktok": ["tiktok.com"],
    "facebook": ["facebook.com", "fb.watch", "fb.gg"],
    "pinterest": ["pinterest.com", "pin.it", "pinterest.co.uk", "pinterest.fr", "pinterest.de",
                  "pinterest.ca", "pinterest.com.au", "pinterest.es", "pinterest.it"],
    "mediafire": ["mediafire.com"],
}
PINTEREST_MEDIA_HOSTS = ["pinimg.com"]
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
QUALITIES = (144, 240, 360, 480, 720, 1080)
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}


@dataclass
class Fetched:
    path: str
    kind: str  # video | audio | image | file
    title: str = ""
    uploader: str = ""
    duration: int = 0
    width: int = 0
    height: int = 0
    extra: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------- URL handling
def extract_url(text: str) -> Optional[str]:
    """First http(s) URL in *text*, upgraded to https."""
    match = _URL_RE.search(text or "")
    if not match:
        return None
    url = match.group(0).rstrip(".,);]")
    return "https://" + url[len("http://"):] if url.lower().startswith("http://") else url


def host_in(url: str, domains: List[str]) -> bool:
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def require_site(url: Optional[str], site: str) -> str:
    if not url:
        raise MediaError("Send a link, for example: https://...")
    if not host_in(url, SITES[site]):
        raise MediaError(f"That link is not a {site.title()} link.")
    return url


def split_quality(args: List[str], default: int = 720):
    """``['480', 'cats']`` -> ``(480, ['cats'])``; unknown numbers stay part of the text."""
    if args and args[0].isdigit() and int(args[0]) in QUALITIES:
        return int(args[0]), args[1:]
    return default, args


# ----------------------------------------------------------------------- yt-dlp
def clean_ytdlp_error(message: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(message)).replace("ERROR: ", "").strip()
    text = re.sub(r"\[[a-z:A-Z0-9_ ]+\]\s*", "", text, count=1) if text.startswith("[") else text
    lowered = text.lower()
    if "login" in lowered or "cookies" in lowered or "private" in lowered:
        return "The site asks for a login. Export your cookies and set REZE_YTDLP_COOKIES=/path/cookies.txt"
    if "unsupported url" in lowered:
        return "This link type is not supported."
    if "video unavailable" in lowered or "not available" in lowered:
        return "The video is unavailable (deleted, private or region-locked)."
    if "larger than max-filesize" in lowered or "file is larger" in lowered:
        return "The file is larger than the allowed size. Try a lower quality."
    return text[:200] or "Download failed."


def build_ytdlp_options(directory: str, *, mode: str, quality: int, max_mb: int,
                        max_seconds: int, cookies: Optional[str] = None) -> dict:
    options = {
        "outtmpl": os.path.join(directory, "%(id)s.%(ext)s"),
        "restrictfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
        "retries": 2,
        "max_filesize": int(max_mb) * 1024 * 1024,
        "default_search": "ytsearch1",
        "geo_bypass": True,
    }
    if cookies and os.path.isfile(cookies):
        options["cookiefile"] = cookies
    if mode == "audio":
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        options["format"] = (f"bv*[height<={quality}][ext=mp4]+ba[ext=m4a]/b[height<={quality}][ext=mp4]/"
                             f"bv*[height<={quality}]+ba/b[height<={quality}]/b")
        options["merge_output_format"] = "mp4"
    if max_seconds:
        options["match_filter"] = f"duration <=? {int(max_seconds)}"  # "?" lets unknown durations pass
    return options


def ytdlp_fetch(target: str, directory: str, *, mode: str = "video", quality: int = 720,
                max_mb: int = 48, max_seconds: int = 3600, cookies: Optional[str] = None) -> Fetched:
    """Blocking download (run it in a worker thread). *target* is a URL or a search phrase."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise MissingDependencyError("yt-dlp is not installed. Install it with: pip install yt-dlp") from exc

    query = target if target.startswith("https://") else f"ytsearch1:{target}"
    options = build_ytdlp_options(directory, mode=mode, quality=quality, max_mb=max_mb,
                                  max_seconds=max_seconds, cookies=cookies)
    if isinstance(options.get("match_filter"), str):
        from yt_dlp.utils import match_filter_func

        options["match_filter"] = match_filter_func(options["match_filter"])
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=True)
    except Exception as exc:  # noqa: BLE001 - yt_dlp raises several DownloadError flavours
        raise MediaError(clean_ytdlp_error(exc)) from exc

    if info and info.get("entries"):
        entries = [e for e in info["entries"] if e]
        info = entries[0] if entries else None
    if not info:
        raise MediaError("Nothing was found for that request.")

    path = None
    downloads = info.get("requested_downloads") or []
    if downloads:
        path = downloads[0].get("filepath")
    if not path or not os.path.isfile(path):
        files = [os.path.join(directory, f) for f in os.listdir(directory)]
        files = [f for f in files if os.path.isfile(f) and not f.endswith((".part", ".ytdl"))]
        path = max(files, key=os.path.getmtime) if files else None
    if not path:
        raise MediaError("The download finished but no file was produced (maybe it exceeded the size limit).")

    return Fetched(
        path=path,
        kind="audio" if mode == "audio" else "video",
        title=str(info.get("title") or "")[:120],
        uploader=str(info.get("uploader") or info.get("channel") or "")[:60],
        duration=int(info.get("duration") or 0),
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        extra={"url": str(info.get("webpage_url") or "")},
    )


# --------------------------------------------------------------------- Pinterest
_META_RE = re.compile(r"<meta\s+[^>]*>", re.I)
_ATTR_RE = re.compile(r'([a-zA-Z:_-]+)\s*=\s*"([^"]*)"')


def parse_og(page: str) -> Dict[str, str]:
    """Collect ``og:*`` / ``twitter:*`` meta tags regardless of attribute order."""
    found: Dict[str, str] = {}
    for tag in _META_RE.findall(page or ""):
        attrs = {k.lower(): htmllib.unescape(v) for k, v in _ATTR_RE.findall(tag)}
        key = attrs.get("property") or attrs.get("name")
        if key and attrs.get("content") and key not in found:
            found[key.lower()] = attrs["content"]
    return found


def pick_pinterest_media(meta: Dict[str, str]):
    """Return ``(url, kind)`` with kind image|video, preferring video."""
    for key in ("og:video:secure_url", "og:video", "twitter:player:stream"):
        value = meta.get(key, "")
        if value.startswith("https://") and host_in(value, PINTEREST_MEDIA_HOSTS):
            return value, "video"
    for key in ("og:image", "twitter:image:src", "twitter:image"):
        value = meta.get(key, "")
        if value.startswith("https://") and host_in(value, PINTEREST_MEDIA_HOSTS):
            # Pinterest serves a 236px/736px thumbnail by default; ask for the original.
            return re.sub(r"/\d+x/", "/originals/", value), "image"
    return None, ""


# --------------------------------------------------------------------- MediaFire
_SCRAMBLED_RE = re.compile(r'data-scrambled-url\s*=\s*"([A-Za-z0-9+/=_-]+)"')
_DIRECT_RE = re.compile(r'https://download[0-9]*\.mediafire\.com/[^\s"\'<>]+', re.I)


def parse_mediafire(page: str) -> Optional[str]:
    """Direct download link from a MediaFire file page (None if not found)."""
    match = _SCRAMBLED_RE.search(page or "")
    if match:
        raw = match.group(1)
        try:
            decoded = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="ignore")
            if decoded.startswith("https://") and host_in(decoded, SITES["mediafire"]):
                return decoded
        except Exception:  # noqa: BLE001
            pass
    match = _DIRECT_RE.search(htmllib.unescape(page or ""))
    return match.group(0) if match else None


def guess_extension(url: str, content_type: str = "") -> str:
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext and len(ext) <= 6:
        return ext
    return {"video/mp4": ".mp4", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(
        (content_type or "").split(";")[0].strip().lower(), ".bin")
