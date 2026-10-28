"""
FFmpeg integration.

FFmpeg is an optional system dependency: Reze checks for it before starting a
conversion and explains how to install it instead of failing halfway. Commands
are always passed as an argument array (never interpolated into a shell string),
subprocesses get a timeout, and stderr is truncated before it reaches a user.
"""

import json
import os
import shutil
import subprocess
from typing import List, Optional

from reze.config import settings
from reze.exceptions import MediaError, MissingDependencyError
from reze.logging_config import logger

DEFAULT_TIMEOUT = 240
MAX_OUTPUT_SECONDS = 300


def ffmpeg_binary() -> Optional[str]:
    configured = (settings.ffmpeg_path or "").strip()
    if configured:
        return configured if os.path.isfile(configured) else shutil.which(configured)
    return shutil.which("ffmpeg")


def ffprobe_binary() -> Optional[str]:
    probe = shutil.which("ffprobe")
    if probe:
        return probe
    ffmpeg = ffmpeg_binary()
    if ffmpeg:
        candidate = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe" if os.name == "nt" else "ffprobe")
        if os.path.isfile(candidate):
            return candidate
    return None


def available() -> bool:
    return ffmpeg_binary() is not None


def require_ffmpeg() -> str:
    binary = ffmpeg_binary()
    if not binary:
        raise MissingDependencyError(
            "FFmpeg is not installed or not on PATH. Install it and restart Reze "
            "(Windows: `winget install Gyan.FFmpeg`, Debian/Ubuntu: `apt install ffmpeg`)."
        )
    return binary


def parse_timestamp(value: str) -> float:
    """Parse ``SS``, ``MM:SS`` or ``HH:MM:SS`` into seconds."""
    text = (value or "").strip()
    if not text:
        raise MediaError("A timestamp is required.")
    parts = text.split(":")
    if len(parts) > 3:
        raise MediaError(f"Invalid timestamp: {value}")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise MediaError(f"Invalid timestamp: {value}") from exc
    if any(number < 0 for number in numbers):
        raise MediaError("Timestamps cannot be negative.")
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def probe_media(path: str) -> dict:
    """Return duration, dimensions and codec information for *path*."""
    binary = ffprobe_binary()
    if not binary:
        raise MissingDependencyError(
            "ffprobe is required to inspect media. Install FFmpeg (it bundles ffprobe)."
        )
    command = [
        binary,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-i", path,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=30, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError("ffprobe timed out while inspecting the file.") from exc
    except OSError as exc:
        raise MediaError(f"Could not start ffprobe: {exc}") from exc

    if completed.returncode != 0:
        raise MediaError("The file is not a supported media container.")

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe returned an unreadable response.") from exc

    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = payload.get("format", {}).get("duration") or (video or {}).get("duration") or 0
    try:
        duration_value = float(duration)
    except (TypeError, ValueError):
        duration_value = 0.0

    return {
        "duration": duration_value,
        "size": int(payload.get("format", {}).get("size", 0) or 0),
        "video": {
            "codec": (video or {}).get("codec_name", ""),
            "width": int((video or {}).get("width", 0) or 0),
            "height": int((video or {}).get("height", 0) or 0),
        }
        if video
        else None,
        "audio": {"codec": (audio or {}).get("codec_name", "")} if audio else None,
    }


def run(args: List[str], timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run one FFmpeg invocation with an argument array and a timeout."""
    binary = require_ffmpeg()
    command = [binary, "-hide_banner", "-loglevel", "error", "-nostdin", *args]
    logger.debug("Running FFmpeg with %d arguments", len(args))
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(
            f"FFmpeg exceeded the {timeout}s limit. Try a shorter clip or lower quality."
        ) from exc
    except OSError as exc:
        raise MediaError(f"Could not start FFmpeg: {exc}") from exc

    if completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()[-3:]
        detail = " | ".join(tail)[:300] or "unknown error"
        raise MediaError(f"FFmpeg failed: {detail}")
    return completed.stdout


def _clip_args(start: Optional[float], duration: Optional[float], end: Optional[float]) -> List[str]:
    args: List[str] = []
    if start is not None:
        if start < 0:
            raise MediaError("The start time cannot be negative.")
        args += ["-ss", f"{start:.3f}"]
    if duration is not None:
        if duration <= 0 or duration > MAX_OUTPUT_SECONDS:
            raise MediaError(f"The duration must be between 0 and {MAX_OUTPUT_SECONDS} seconds.")
        args += ["-t", f"{duration:.3f}"]
    elif end is not None:
        if end <= 0:
            raise MediaError("The end time must be positive.")
        args += ["-to", f"{end:.3f}"]
    return args


def to_gif(
    source: str,
    destination: str,
    fps: int = 12,
    width: int = 480,
    start: Optional[float] = None,
    duration: Optional[float] = None,
) -> str:
    fps = max(5, min(int(fps), 30))
    width = max(80, min(int(width), 1280))
    args = ["-y", *_clip_args(start, duration, None), "-i", source,
            "-vf", f"fps={fps},scale={width}:-1:flags=lanczos",
            "-loop", "0", destination]
    run(args)
    _require_output(destination)
    return destination


def to_video(source: str, destination: str) -> str:
    args = ["-y", "-i", source, "-movflags", "+faststart",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", destination]
    run(args)
    _require_output(destination)
    return destination


def to_audio(source: str, destination: str, bitrate: str = "128k") -> str:
    args = ["-y", "-i", source, "-vn", "-c:a", "libmp3lame", "-b:a", bitrate, destination]
    run(args)
    _require_output(destination)
    return destination


def trim(
    source: str,
    destination: str,
    start: float,
    end: Optional[float] = None,
    duration: Optional[float] = None,
) -> str:
    args = ["-y"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", source]
    if duration is not None:
        args += _clip_args(None, duration, None)
    elif end is not None:
        if end <= start:
            raise MediaError("The end time must be after the start time.")
        args += ["-t", f"{(end - start):.3f}"]
    else:
        raise MediaError("Provide an end time or a duration for the trim.")
    args += ["-c", "copy", destination]
    run(args, timeout=180)
    _require_output(destination)
    return destination


def change_speed(source: str, destination: str, factor: float, is_video: bool = True) -> str:
    if not 0.25 <= factor <= 4.0:
        raise MediaError("The speed factor must be between 0.25 and 4.0.")
    atempo = []
    remaining = factor
    # atempo accepts 0.5-2.0 per instance; chain filters for larger factors.
    while remaining > 2.0:
        atempo.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        atempo.append("atempo=0.5")
        remaining /= 0.5
    atempo.append(f"atempo={remaining:.4f}")

    if is_video:
        filter_complex = f"[0:v]setpts={1.0 / factor:.6f}*PTS[v];[0:a]{','.join(atempo)}[a]"
        args = ["-y", "-i", source, "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "23", "-c:a", "aac", destination]
    else:
        args = ["-y", "-i", source, "-filter:a", ",".join(atempo), "-c:a", "libmp3lame", destination]
    run(args)
    _require_output(destination)
    return destination


def compress_video(source: str, destination: str, crf: int = 28, width: Optional[int] = None) -> str:
    crf = max(18, min(int(crf), 40))
    filters = []
    if width:
        width = max(160, min(int(width), 1920))
        filters.append(f"scale={width}:-2")
    args = ["-y", "-i", source]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
             "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", destination]
    run(args, timeout=300)
    _require_output(destination)
    return destination


def extract_frame(source: str, destination: str, at: float = 1.0) -> str:
    if at < 0:
        raise MediaError("The frame timestamp cannot be negative.")
    args = ["-y", "-ss", f"{at:.3f}", "-i", source, "-frames:v", "1", "-q:v", "2", destination]
    run(args, timeout=60)
    _require_output(destination)
    return destination


def _require_output(path: str) -> None:
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise MediaError("FFmpeg did not produce an output file.")
    limit = int(settings.media_max_output_mb) * 1024 * 1024
    if os.path.getsize(path) > limit:
        raise MediaError(
            f"The result is larger than the {settings.media_max_output_mb} MB output limit."
        )
