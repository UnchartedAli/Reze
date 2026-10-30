"""Voice Intelligence: transcribe voice notes through an OpenAI-compatible API.

Optional feature. It uses the same credentials as the AI gateway, sends only
the audio file the owner explicitly asks to transcribe, and never logs the
transcript or the key. Without a provider the command reports "unavailable".
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, Optional

from reze.config import settings
from reze.database import db
from reze.logging_config import logger
from reze.search import universal


class VoiceUnavailable(Exception):
    """Raised when transcription is not configured or not possible."""


def available() -> bool:
    return bool(settings.ai_api_key)


def _endpoint() -> str:
    base = (settings.ai_base_url or "https://api.openai.com/v1").rstrip("/")
    return f"{base}/audio/transcriptions"


def _multipart(fields: Dict[str, str], filename: str, payload: bytes) -> tuple:
    boundary = f"----reze{uuid.uuid4().hex}"
    chunks = []
    for name, value in fields.items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode(
                "utf-8"
            )
        )
    chunks.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        + payload
        + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(chunks)


def _transcribe_sync(path: str) -> str:
    if not available():
        raise VoiceUnavailable("Configure REZE_AI_API_KEY to enable voice transcription.")
    if not os.path.isfile(path):
        raise VoiceUnavailable("The audio file is missing.")
    size = os.path.getsize(path)
    limit = max(1, int(settings.voice_max_mb)) * 1024 * 1024
    if size > limit:
        raise VoiceUnavailable(f"Audio is larger than the {settings.voice_max_mb} MB limit.")
    with open(path, "rb") as handle:
        payload = handle.read()

    boundary, body = _multipart(
        {"model": settings.voice_model or "whisper-1", "response_format": "json"},
        os.path.basename(path),
        payload,
    )
    request = urllib.request.Request(
        _endpoint(),
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.ai_api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=max(30, int(settings.ai_timeout_seconds))) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise VoiceUnavailable(f"Transcription failed with HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise VoiceUnavailable(f"Transcription failed: {exc}") from exc
    text = str(data.get("text") or "").strip()
    if not text:
        raise VoiceUnavailable("The provider returned an empty transcript.")
    return text


async def transcribe(path: str) -> str:
    """Transcribe an audio file without blocking the event loop."""
    return await asyncio.to_thread(_transcribe_sync, path)


class VoiceService:
    def store(self, transcript: str, duration_seconds: int = 0, chat_id: int = 0, message_id: int = 0) -> int:
        text = (transcript or "").strip()
        if not text:
            raise ValueError("The transcript is empty.")
        voice_id = db.execute(
            "INSERT INTO voice_notes (duration_seconds, transcript, chat_id, message_id) "
            "VALUES (?, ?, ?, ?)",
            (max(0, int(duration_seconds or 0)), text[:20000], int(chat_id or 0), int(message_id or 0)),
        )
        universal.index("document", f"voice:{voice_id}", "Voice note", text, "voice")
        logger.info("Voice note #%s transcribed (%d chars).", voice_id, len(text))
        return voice_id

    def recent(self, limit: int = 10):
        return db.query(
            "SELECT id, created_at, duration_seconds, chat_id, message_id FROM voice_notes "
            "ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 50)),),
        )


voice_service = VoiceService()

__all__ = ["VoiceService", "VoiceUnavailable", "available", "transcribe", "voice_service"]
