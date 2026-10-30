"""
Real Telegram stickers through the Bot API.

Why a bot? Sending a .webp as a *file* only produces a document. A genuine sticker
belongs to a sticker set, and Telegram only lets bots create/extend sets through an
official API. Reze therefore keeps a personal pack on your account, owned through a
small bot of yours:

1. create a bot with @BotFather and put its token in ``REZE_STICKER_BOT_TOKEN``;
2. open the bot once and press **Start** (Telegram lets a bot act for users who started it);
3. ``.sticker`` now adds the converted sticker to your pack and sends the real sticker.

Sets are homogeneous, so images go to ``reze_<id>_s<N>`` and video stickers to
``reze_<id>_v<N>`` (N grows automatically when a set is full).
"""

import json
import os
import re
import uuid
from typing import Any, Dict, Optional, Tuple

from reze.core import http
from reze.exceptions import MediaError

API_HOST = "api.telegram.org"
MAX_STICKERS_PER_SET = 120
_username_cache: Dict[str, str] = {}


class StickerBotError(MediaError):
    """A Bot API refusal, phrased for the owner."""


def token() -> Optional[str]:
    value = os.environ.get("REZE_STICKER_BOT_TOKEN", "").strip()
    return value or None


def friendly(description: str) -> str:
    text = (description or "").lower()
    if "user not found" in text or "chat not found" in text or "peer_id_invalid" in text or "forbidden" in text:
        return "Open your sticker bot in Telegram and press Start once, then try again."
    if "unauthorized" in text or "not found" == text.strip():
        return "The sticker bot token is invalid. Check REZE_STICKER_BOT_TOKEN."
    if "stickers_too_much" in text or "too much" in text or "too many" in text:
        return "This sticker set is full."
    if "stickerset_invalid" in text or "sticker set name is already occupied" in text:
        return description
    return description or "Telegram refused the request."


async def api(bot_token: str, method: str, fields: Optional[Dict[str, str]] = None,
              files: Optional[Dict[str, Tuple[str, bytes, str]]] = None) -> Any:
    url = f"https://{API_HOST}/bot{bot_token}/{method}"
    status, raw = await http.post_form(url, fields or {}, files, allowed=[API_HOST])
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise StickerBotError("Telegram returned an unreadable answer.") from exc
    if not data.get("ok"):
        raise StickerBotError(friendly(str(data.get("description", ""))))
    return data.get("result")


async def bot_username(bot_token: str) -> str:
    if bot_token not in _username_cache:
        me = await api(bot_token, "getMe")
        _username_cache[bot_token] = str(me["username"])
    return _username_cache[bot_token]


def short_name(owner_id: int, video: bool, index: int, username: str, tag: str = "") -> str:
    """Valid set name: a-z0-9_, starts with a letter, no double underscores, ends with _by_<bot>."""
    middle = tag or f"{'v' if video else 's'}{index}"
    name = f"reze_{owner_id}_{middle}_by_{username}".lower()
    return re.sub(r"_+", "_", name)[:64]


def _input_sticker(video: bool, emoji: str) -> str:
    return json.dumps({"sticker": "attach://file", "format": "video" if video else "static", "emoji_list": [emoji]})


def _file_part(path: str, video: bool) -> Dict[str, Tuple[str, bytes, str]]:
    with open(path, "rb") as handle:
        content = handle.read()
    return {"file": (os.path.basename(path), content, "video/webm" if video else "image/webp")}


async def set_exists(bot_token: str, name: str) -> bool:
    try:
        await api(bot_token, "getStickerSet", {"name": name})
        return True
    except StickerBotError as exc:
        if "stickerset_invalid" in str(exc).lower():
            return False
        raise


async def create_set(bot_token: str, owner_id: int, name: str, title: str, path: str, emoji: str, video: bool) -> None:
    await api(bot_token, "createNewStickerSet",
              {"user_id": str(owner_id), "name": name, "title": title[:64], "stickers": json.dumps([json.loads(_input_sticker(video, emoji))])},
              _file_part(path, video))


async def add_to_set(bot_token: str, owner_id: int, name: str, path: str, emoji: str, video: bool) -> None:
    await api(bot_token, "addStickerToSet",
              {"user_id": str(owner_id), "name": name, "sticker": _input_sticker(video, emoji)},
              _file_part(path, video))


# ---- which numbered set is the current one (persisted so restarts keep adding to the same pack)
def _get_index(video: bool) -> int:
    from reze.database import db

    try:
        return max(1, int(db.get_setting(f"stickerbot:index:{'v' if video else 's'}") or 1))
    except (TypeError, ValueError):
        return 1


def _set_index(video: bool, index: int) -> None:
    from reze.database import db

    db.set_setting(f"stickerbot:index:{'v' if video else 's'}", str(index))


async def add_to_personal_pack(owner_id: int, path: str, emoji: str, video: bool) -> str:
    """Add the file to the owner's current personal pack (creating or rolling over as needed). Returns the set name."""
    bot_token = token()
    if not bot_token:
        raise StickerBotError("REZE_STICKER_BOT_TOKEN is not set.")
    username = await bot_username(bot_token)
    index = _get_index(video)
    for _ in range(3):  # at most: add, roll over to a new set, create it
        name = short_name(owner_id, video, index, username)
        title = f"Reze {'Video ' if video else ''}Stickers" + (f" {index}" if index > 1 else "")
        if not await set_exists(bot_token, name):
            await create_set(bot_token, owner_id, name, title, path, emoji, video)
            _set_index(video, index)
            return name
        try:
            await add_to_set(bot_token, owner_id, name, path, emoji, video)
            _set_index(video, index)
            return name
        except StickerBotError as exc:
            if "full" in str(exc).lower():
                index += 1
                continue
            raise
    raise StickerBotError("Could not find a set with free space.")


async def create_named_pack(owner_id: int, title: str, path: str, emoji: str, video: bool = False) -> str:
    bot_token = token()
    if not bot_token:
        raise StickerBotError("REZE_STICKER_BOT_TOKEN is not set.")
    username = await bot_username(bot_token)
    name = short_name(owner_id, video, 0, username, tag=uuid.uuid4().hex[:8])
    await create_set(bot_token, owner_id, name, title, path, emoji, video)
    return name


async def add_to_named_pack(owner_id: int, set_name: str, path: str, emoji: str, video: bool = False) -> str:
    bot_token = token()
    if not bot_token:
        raise StickerBotError("REZE_STICKER_BOT_TOKEN is not set.")
    username = await bot_username(bot_token)
    name = set_name.lower()
    if not name.endswith(f"_by_{username.lower()}"):
        name = re.sub(r"_+", "_", f"{name}_by_{username}".lower())
    await add_to_set(bot_token, owner_id, name, path, emoji, video)
    return name


async def fetch_last_sticker(client: Any, set_name: str):
    """The newest sticker document of the set, via MTProto (so it can be re-sent as a real sticker)."""
    from telethon.tl import functions, types

    result = await client(functions.messages.GetStickerSetRequest(
        stickerset=types.InputStickerSetShortName(short_name=set_name), hash=0))
    documents = list(getattr(result, "documents", []) or [])
    if not documents:
        raise StickerBotError("The sticker was added, but Telegram has not published it yet. Try .sticker again.")
    return documents[-1]
