"""
Real Telegram sticker-set operations.

These functions call the MTProto requests that actually create sticker sets
(``messages.CreateStickerSet`` / ``messages.AddStickerToSet``) through the
authenticated userbot account. Nothing here fabricates a link: the pack URL is
derived from the ``short_name`` returned by Telegram after it confirms creation.

Verified against Telethon 1.45.0:

* ``telethon.tl.functions.stickers.CreateStickerSetRequest(user_id, title, short_name, stickers, masks=None)``
* ``telethon.tl.functions.stickers.AddStickerToSetRequest(stickerset, sticker)``
* ``telethon.tl.types.InputStickerSetItem(document, emoji, mask_coords=None, keywords=None)``
"""

import os
import re
import uuid
from typing import Any, Dict, Optional

from reze.exceptions import MediaError, TelegramAPIError

SHORT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def validate_short_name(short_name: str) -> str:
    name = (short_name or "").strip()
    if not SHORT_NAME_RE.match(name):
        raise ValueError(
            "Sticker set links must be 1-64 characters, start with a letter, "
            "and contain only letters, digits or underscores."
        )
    return name


def generate_short_name(base: str = "reze") -> str:
    """A collision-resistant, Telegram-valid short name."""
    slug = re.sub(r"[^A-Za-z0-9_]", "", (base or "reze"))
    if not slug or not slug[0].isalpha():
        slug = "reze" + slug
    slug = slug[:40]
    return f"{slug}_{uuid.uuid4().hex[:10]}"


def validate_sticker_asset(path: str) -> None:
    """Ensure the asset is the static WebP format Telegram accepts."""
    from reze.media import images

    if not os.path.isfile(path):
        raise MediaError("The generated sticker file is missing.")
    if not images.available():
        raise MediaError("Pillow is required to validate the sticker asset.")
    with images.Image.open(path) as image:
        if image.format != "WEBP":
            raise MediaError("Telegram static stickers must be WebP files.")
        if image.size != (512, 512):
            raise MediaError("Telegram static stickers must be exactly 512x512 pixels.")
    if os.path.getsize(path) > 512 * 1024:
        raise MediaError("The sticker asset exceeds Telegram's 512 KB limit.")


async def _resolve_user(client: Any) -> Any:
    me = await client.get_me()
    if me is None:
        raise TelegramAPIError("The Telegram account is not authorized.")
    try:
        return await client.get_input_entity(me)
    except Exception:
        return me


def _emoji_argument(emoji: str) -> str:
    value = (emoji or "").strip()
    if not value:
        raise MediaError("A sticker emoji is required, for example .stickerpack 🙂")
    if len(value) > 8:
        raise MediaError("Use a single emoji for the sticker.")
    return value


async def create_sticker_set(
    client: Any,
    title: str,
    short_name: str,
    sticker_path: str,
    emoji: str = "🙂",
) -> Dict[str, Any]:
    """
    Create a new sticker set with one sticker and return Telegram's result.

    The returned URL is only built after the request succeeded, using the
    ``short_name`` Telegram confirmed.
    """
    from telethon.tl.functions.stickers import CreateStickerSetRequest
    from telethon.tl.types import InputStickerSetItem

    title = (title or "").strip()
    if not 1 <= len(title) <= 64:
        raise MediaError("The sticker set title must be 1-64 characters.")
    short_name = validate_short_name(short_name)
    validate_sticker_asset(sticker_path)
    emoji = _emoji_argument(emoji)

    user = await _resolve_user(client)
    uploaded = await client.upload_file(sticker_path)
    item = InputStickerSetItem(document=uploaded, emoji=emoji)

    result = await client(
        CreateStickerSetRequest(
            user_id=user,
            title=title,
            short_name=short_name,
            stickers=[item],
            masks=False,
        )
    )

    sticker_set = getattr(result, "set", None)
    confirmed_name = getattr(sticker_set, "short_name", "") or short_name
    return {
        "short_name": confirmed_name,
        "title": getattr(sticker_set, "title", title),
        "count": int(getattr(sticker_set, "count", 1) or 1),
        "url": f"https://t.me/addstickers/{confirmed_name}",
        "emoji": emoji,
    }


async def add_sticker_to_set(
    client: Any,
    short_name: str,
    sticker_path: str,
    emoji: str = "🙂",
) -> Dict[str, Any]:
    """Add one sticker to an existing set owned by the current account."""
    from telethon.tl.functions.stickers import AddStickerToSetRequest
    from telethon.tl.types import InputStickerSetItem, InputStickerSetShortName

    validate_short_name(short_name)
    validate_sticker_asset(sticker_path)
    emoji = _emoji_argument(emoji)

    uploaded = await client.upload_file(sticker_path)
    item = InputStickerSetItem(document=uploaded, emoji=emoji)
    await client(
        AddStickerToSetRequest(
            stickerset=InputStickerSetShortName(short_name=short_name),
            sticker=item,
        )
    )
    return {
        "short_name": short_name,
        "url": f"https://t.me/addstickers/{short_name}",
        "emoji": emoji,
    }
