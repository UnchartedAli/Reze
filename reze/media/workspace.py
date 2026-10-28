"""
Temporary workspace handling for media operations.

Every conversion gets its own directory under ``REZE_MEDIA_WORK_DIR`` (default
``data/media``) with generated file names, so user-supplied names can never
escape the directory or overwrite another file. Directories are removed in a
``finally`` block by the command that created them.
"""

import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from reze.config import settings
from reze.exceptions import MediaError
from reze.logging_config import logger

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".mp4", ".webm", ".mov", ".mkv", ".avi",
    ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".flac",
}


def safe_filename(name: str, fallback_extension: str = ".bin") -> str:
    """Reduce an arbitrary name to a safe basename inside the workspace."""
    base = os.path.basename(str(name or "")).strip()
    base = _SAFE_RE.sub("_", base).strip("._-")
    if not base:
        base = uuid.uuid4().hex[:10]
    extension = os.path.splitext(base)[1].lower()
    if extension not in _ALLOWED_EXTENSIONS:
        base += fallback_extension
    return base[:96]


@dataclass
class MediaResult:
    """A produced file plus the metadata needed to send it."""

    path: str
    kind: str = "document"
    caption: str = ""
    force_document: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0


class MediaWorkspace:
    """An isolated scratch directory for one media operation."""

    def __init__(self, prefix: str = "job"):
        root = settings.media_work_path
        os.makedirs(root, exist_ok=True)
        self.directory = os.path.join(root, f"{prefix}-{uuid.uuid4().hex[:8]}-{int(time.time())}")
        os.makedirs(self.directory, exist_ok=True)
        self._cleaned = False

    def path(self, name: str, extension: str = ".bin") -> str:
        return os.path.join(self.directory, safe_filename(name, extension))

    def child(self, name: str) -> str:
        """Path for a generated file, always inside the workspace directory."""
        filename = safe_filename(name)
        target = os.path.abspath(os.path.join(self.directory, filename))
        if not target.startswith(os.path.abspath(self.directory) + os.sep):
            raise MediaError("Refusing to write outside the media workspace.")
        return target

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        try:
            shutil.rmtree(self.directory, ignore_errors=True)
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.debug("Could not remove the media workspace %s: %s", self.directory, exc)

    def __enter__(self) -> "MediaWorkspace":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()


def ensure_size(path: str, limit_mb: Optional[int] = None, label: str = "File") -> int:
    """Validate that *path* exists and is under the configured input limit."""
    if not os.path.isfile(path):
        raise MediaError(f"{label} is missing on disk.")
    size = os.path.getsize(path)
    if size <= 0:
        raise MediaError(f"{label} is empty.")
    limit = int(limit_mb if limit_mb is not None else settings.media_max_input_mb)
    if size > limit * 1024 * 1024:
        raise MediaError(f"{label} is {size / 1048576:.1f} MB; the limit is {limit} MB.")
    return size


async def download_reply_media(ctx: Any, workspace: MediaWorkspace) -> str:
    """
    Download the media attached to the replied-to message.

    Only the media of a replied message is downloaded: Reze never scans or
    bulk-downloads chat history for media commands.
    """
    reply = await ctx.get_reply_message()
    if reply is None:
        raise MediaError("Reply to a message that contains media, then run the command again.")
    media = getattr(reply, "media", None)
    if media is None:
        raise MediaError("The replied-to message has no media attached.")

    filename = getattr(getattr(reply, "file", None), "name", "") or ""
    extension = os.path.splitext(filename)[1] or ".bin"
    target = os.path.join(workspace.directory, safe_filename(filename or "input", extension))

    client = ctx.client
    if client is None or not hasattr(client, "download_media"):
        raise MediaError("No Telegram client is available to download the media.")

    try:
        downloaded = await client.download_media(reply, file=target)
    except Exception as exc:  # noqa: BLE001 - Telegram/download failures
        raise MediaError(f"Could not download the media: {exc}") from exc

    path = downloaded if isinstance(downloaded, str) else target
    if not os.path.isfile(path):
        raise MediaError("Telegram did not return the downloaded file.")
    ensure_size(path)
    return path
