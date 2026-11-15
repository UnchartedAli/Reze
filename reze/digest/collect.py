"""Telegram access for Channel Digest (Telethon).

Only channels already selected by the owner are read. Listing dialogs reads
titles and ids only, never message content.

Telethon methods used: ``iter_dialogs``, ``get_entity``, ``get_messages`` and
``iter_messages``. These follow the Telethon documentation. They are not
exercised against a live account in this repository's test suite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reze.digest.models import SourceMessage
from reze.digest.text import message_link


def peer_id_for_channel(entity: Any) -> int:
    """Telegram's marked id for a channel or supergroup: -100<channel id>."""
    return -(1000000000000 + int(entity.id))


async def list_broadcast_channels(client: Any) -> List[Dict[str, Any]]:
    found = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if getattr(entity, "broadcast", False):
            found.append(
                {
                    "chat_id": peer_id_for_channel(entity),
                    "title": getattr(entity, "title", "") or getattr(dialog, "name", "") or "",
                    "username": getattr(entity, "username", "") or "",
                }
            )
    return found


async def resolve_channel(client: Any, reference: str) -> Dict[str, Any]:
    ref = (reference or "").strip()
    if not ref:
        raise ValueError("Give a channel as @username or as its numeric id.")
    target: Any
    if ref.lstrip("-").isdigit():
        target = int(ref)
    else:
        target = ref if ref.startswith("@") else f"@{ref}"
    entity = await client.get_entity(target)
    if not getattr(entity, "broadcast", False):
        raise ValueError("Only broadcast channels can be added. Groups and private chats are not supported.")
    return {
        "chat_id": peer_id_for_channel(entity),
        "title": getattr(entity, "title", "") or "",
        "username": getattr(entity, "username", "") or "",
    }


async def latest_message_id(client: Any, chat_id: int) -> int:
    messages = await client.get_messages(chat_id, limit=1)
    if not messages:
        return 0
    return int(messages[0].id)


async def fetch_new(client: Any, chat_id: int, min_id: int, limit: int) -> List[Any]:
    """Messages with id greater than *min_id*, oldest first, at most *limit* of them."""
    raw = []
    async for message in client.iter_messages(chat_id, min_id=min_id, limit=limit, reverse=True):
        raw.append(message)
    return raw


def flood_wait_seconds(exc: BaseException) -> Optional[int]:
    """Seconds Telegram asked us to wait, or None when *exc* is not a flood wait."""
    if type(exc).__name__ != "FloodWaitError":
        return None
    try:
        return max(0, int(getattr(exc, "seconds", 0) or 0))
    except (TypeError, ValueError):
        return 60


def _naive_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    return datetime(1970, 1, 1)


def to_source(raw: Any, channel: Dict[str, Any]) -> SourceMessage:
    text = getattr(raw, "message", "") or ""
    media = getattr(raw, "media", None)
    media_kind = ""
    if media is not None and type(media).__name__ != "MessageMediaWebPage":
        media_kind = type(media).__name__.replace("MessageMedia", "").lower()
    if not text.strip() and media_kind:
        text = f"[{media_kind}]"
    return SourceMessage(
        chat_id=int(channel["chat_id"]),
        title=channel.get("title", "") or "",
        username=channel.get("username", "") or "",
        priority=int(channel.get("priority", 5)),
        message_id=int(raw.id),
        date=_naive_utc(getattr(raw, "date", None)),
        text=text,
        is_forward=bool(getattr(raw, "fwd_from", None)),
        media_kind=media_kind,
        link=message_link(int(channel["chat_id"]), channel.get("username", "") or "", int(raw.id)),
    )


__all__ = [
    "fetch_new",
    "flood_wait_seconds",
    "latest_message_id",
    "list_broadcast_channels",
    "peer_id_for_channel",
    "resolve_channel",
    "to_source",
]
