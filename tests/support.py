"""
Shared test fixtures for Reze.

The environment is prepared *before* any ``reze`` module is imported so the
configuration singleton points at a throw-away SQLite database and a temporary
data directory. Nothing in the suite requires Telegram or paid AI credentials.
"""

import asyncio
import os
import shutil
import tempfile

TEST_DATA_DIR = tempfile.mkdtemp(prefix="reze-tests-")
os.environ["REZE_DATA_DIR"] = TEST_DATA_DIR
os.environ["REZE_DATABASE_URL"] = f"sqlite:///{os.path.join(TEST_DATA_DIR, 'reze-test.db')}"
os.environ["REZE_PANEL_PASSWORD"] = "test-password"
os.environ["REZE_OWNER_ID"] = "4242"
os.environ["REZE_LOG_LEVEL"] = "CRITICAL"
os.environ["REZE_TASK_TIMEOUT_SECONDS"] = "20"
os.environ.pop("REZE_API_ID", None)
os.environ.pop("REZE_SESSION_STRING", None)

from reze.command_router import CommandContext  # noqa: E402


def run(coro):
    """Run a coroutine in a fresh event loop."""
    return asyncio.run(coro)


def cleanup():
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)


class DummyFile:
    def __init__(self, name="", size=1024, mime_type="image/png"):
        self.name = name
        self.size = size
        self.mime_type = mime_type


class DummyMessage:
    """A message double covering the attributes the router and commands use."""

    def __init__(
        self,
        text="",
        chat_id=-100200,
        sender_id=4242,
        message_id=10,
        media=None,
        reply=None,
        out=False,
        file=None,
    ):
        self.message = text
        self.text = text
        self.chat_id = chat_id
        self.sender_id = sender_id
        self.id = message_id
        self.media = media
        self.file = file if file is not None else (DummyFile() if media else None)
        self.out = out
        self.reply_to_msg_id = getattr(reply, "id", None) if reply else None
        self.is_group = bool(chat_id and chat_id < 0)
        self._reply = reply
        self.replies = []
        self.edits = []
        self.deleted = False

    async def reply(self, text):
        self.replies.append(text)
        return self

    async def edit(self, text):
        self.edits.append(text)
        return self

    async def delete(self):
        self.deleted = True

    async def get_reply_message(self):
        return self._reply


class DummyClient:
    """Minimal Telethon-like client used by command and media tests."""

    def __init__(self, downloads=None, entities=None):
        self.sent = []
        self.sent_files = []
        self.deleted_messages = []
        self.permission_updates = []
        self.profile_updates = []
        self.requests = []
        self.downloads = downloads or []
        self.entities = entities or {}
        self._me = type("Me", (), {"id": 4242, "username": "reze", "first_name": "Reze"})()

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))
        return DummyMessage(text=text, chat_id=chat_id)

    async def send_file(self, entity, file, **kwargs):
        # Same positional signature as Telethon: send_file(entity, file, *, ...).
        # (The old **kwargs-only double hid a real "missing 'entity'" bug.)
        self.sent_files.append({"entity": entity, "file": file, **kwargs})
        return DummyMessage(text=str(kwargs.get("caption", "")))

    async def download_media(self, message, file=None):
        if self.downloads:
            return self.downloads.pop(0)
        return file

    async def get_reply_message(self):
        return None

    async def get_me(self):
        return self._me

    async def get_input_entity(self, entity):
        return "input-user"

    async def get_entity(self, entity):
        if isinstance(entity, str):
            raise ValueError("no such entity")
        if hasattr(entity, "id"):
            return entity
        return self.entities.get(entity, self._me)

    async def upload_file(self, path, **kwargs):
        self.uploaded = path
        return "input-file"

    async def edit_permissions(self, chat_id, user_id, rights):
        self.permission_updates.append((chat_id, user_id, rights))

    async def kick_participant(self, chat_id, user_id):
        self.permission_updates.append((chat_id, user_id, "kick"))

    async def pin_message(self, chat_id, message_id):
        self.permission_updates.append((chat_id, message_id, "pin"))

    async def unpin_message(self, chat_id):
        self.permission_updates.append((chat_id, None, "unpin"))

    async def delete_messages(self, chat_id, ids):
        self.deleted_messages.append((chat_id, list(ids)))

    async def set_slow_mode(self, chat_id, seconds):
        self.permission_updates.append((chat_id, seconds, "slowmode"))

    async def iter_messages(self, chat_id, limit=None, search=None):
        for text in ["deploy finished", "random note", "deploy again"]:
            message = DummyMessage(text=text)
            yield message

    async def __call__(self, request):
        self.requests.append(request)
        set_short_name = getattr(request, "short_name", None)
        if set_short_name:
            sticker_set = type(
                "StickerSet", (), {"short_name": set_short_name, "title": request.title, "count": 1}
            )()
            return type("Result", (), {"set": sticker_set})()
        return type("Ok", (), {})()


def make_context(
    text=".command",
    args=None,
    client=None,
    reply=None,
    chat_id=-100200,
    sender_id=4242,
    handler=None,
):
    """Build a CommandContext around dummy message objects."""
    message = DummyMessage(text=text, chat_id=chat_id, sender_id=sender_id, reply=reply)
    return CommandContext(
        message=message,
        client=client if client is not None else DummyClient(),
        command_name=text.lstrip(".").split(" ")[0] or "test",
        args=list(args or []),
        raw_text=text.lstrip("."),
        command=handler,
    )
