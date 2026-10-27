"""
Dot Command Router for Reze Userbot.
Handles parsing, aliases, case-insensitivity, permissions, and execution logging.
"""

import inspect
import shlex
import time
from typing import Callable, Dict, List, Optional, Any
from reze.config import settings
from reze.logging_config import logger
from reze.permissions import PermissionManager
from reze.exceptions import CommandExecutionError

class CommandContext:
    def __init__(self, message: Any, client: Any, command_name: str, args: List[str], raw_text: str):
        self.message = message
        self.client = client
        self.command_name = command_name
        self.args = args
        self.raw_text = raw_text
        self.chat_id = getattr(message, "chat_id", None)
        self.sender_id = getattr(message, "sender_id", None)
        self.is_reply = bool(getattr(message, "reply_to_msg_id", None))

    async def reply(self, text: str):
        """Helper to reply to the command message."""
        if hasattr(self.message, "reply"):
            return await self.message.reply(text)
        elif hasattr(self.message, "edit"):
            return await self.message.edit(text)
        elif hasattr(self.client, "send_message"):
            return await self.client.send_message(self.chat_id, text)
        return text

    async def get_target_user_id(self) -> Optional[int]:
        """Resolve target user from reply or first argument."""
        if self.is_reply:
            if hasattr(self.message, "get_reply_message"):
                reply_msg = await self.message.get_reply_message()
                if reply_msg and hasattr(reply_msg, "sender_id"):
                    return reply_msg.sender_id
            elif hasattr(self.message, "reply_to_user_id"):
                return self.message.reply_to_user_id
        if self.args:
            # Check if arg is numeric user id or username
            arg = self.args[0]
            if arg.isdigit():
                return int(arg)
        return None


class Command:
    def __init__(
        self,
        name: str,
        handler: Callable,
        category: str = "General",
        description: str = "",
        usage: str = "",
        aliases: Optional[List[str]] = None,
        owner_only: bool = False,
        admin_only: bool = False,
        group_only: bool = False
    ):
        self.name = name.lower()
        self.handler = handler
        self.category = category
        self.description = description
        self.usage = usage or f".{name}"
        self.aliases = [a.lower() for a in (aliases or [])]
        self.owner_only = owner_only
        self.admin_only = admin_only
        self.group_only = group_only


class CommandRouter:
    def __init__(self, default_prefix: str = "."):
        self.prefix = default_prefix
        self.commands: Dict[str, Command] = {}
        self.aliases_map: Dict[str, str] = {}
        self.total_executed = 0
        self.errors_count = 0
        self.start_time = time.time()

    def register(
        self,
        name: str,
        category: str = "General",
        description: str = "",
        usage: str = "",
        aliases: Optional[List[str]] = None,
        owner_only: bool = False,
        admin_only: bool = False,
        group_only: bool = False
    ):
        """Decorator to register a command."""
        def decorator(handler: Callable):
            cmd = Command(
                name=name,
                handler=handler,
                category=category,
                description=description,
                usage=usage,
                aliases=aliases,
                owner_only=owner_only,
                admin_only=admin_only,
                group_only=group_only
            )
            self.commands[cmd.name] = cmd
            for alias in cmd.aliases:
                self.aliases_map[alias] = cmd.name
            return handler
        return decorator

    def unregister(self, name: str):
        """Unregister a command and its aliases."""
        name = name.lower()
        if name in self.commands:
            cmd = self.commands.pop(name)
            for a in cmd.aliases:
                self.aliases_map.pop(a, None)

    async def handle_message(self, message: Any, client: Any) -> Optional[Any]:
        """Parse and execute dot command if present."""
        text = getattr(message, "message", getattr(message, "text", ""))
        if not text or not text.startswith(self.prefix):
            return None

        # Clean command text
        raw_cmd = text[len(self.prefix):].strip()
        if not raw_cmd:
            return None

        parts = raw_cmd.split()
        cmd_trigger = parts[0].lower()
        args = parts[1:]

        # Resolve command via map
        canonical_name = self.aliases_map.get(cmd_trigger, cmd_trigger)
        command = self.commands.get(canonical_name)

        if not command:
            return None

        sender_id = getattr(message, "sender_id", 0)
        chat_id = getattr(message, "chat_id", 0)

        # 1. Check Owner Only
        if command.owner_only and not PermissionManager.is_owner(sender_id):
            logger.warning("Unauthorized execution attempt for .%s by %d", canonical_name, sender_id)
            return None

        # 2. Check Admin Only
        if command.admin_only:
            can_admin = await PermissionManager.can_moderate(client, chat_id, sender_id)
            if not can_admin:
                return await message.reply("⚠️ شما دسترسی مدیریتی لازم برای این دستور را ندارید.")

        # 3. Check Group Only
        is_group = bool(getattr(message, "is_group", False) or (chat_id and chat_id < 0))
        if command.group_only and not is_group:
            return await message.reply("⚠️ این دستور فقط در گروه‌ها و سوپرگروه‌ها قابل استفاده است.")

        ctx = CommandContext(
            message=message,
            client=client,
            command_name=canonical_name,
            args=args,
            raw_text=raw_cmd
        )

        try:
            self.total_executed += 1
            logger.info("Executing command .%s by %s in chat %s", canonical_name, sender_id, chat_id)
            return await command.handler(ctx)
        except Exception as e:
            self.errors_count += 1
            logger.error("Error executing .%s: %s", canonical_name, e, exc_info=True)
            return await ctx.reply(f"❌ خطا در اجرای دستور: {str(e)}")

router = CommandRouter(default_prefix=settings.default_prefix)
