"""
Dot command router for Reze.

Responsibilities:

* parse ``.command args...`` from an incoming message;
* resolve aliases and enforce owner/admin/group permissions;
* apply per-command cooldowns;
* execute the handler with a :class:`CommandContext`;
* deliver long responses in Telegram-safe chunks;
* register plugin ownership so duplicate commands can be rejected;
* never let a handler traceback escape into the Telethon event loop.
"""

import asyncio
import os
import inspect
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from reze.config import settings
from reze.exceptions import CommandExecutionError, DuplicateCommandError
from reze.logging_config import logger
from reze.permissions import PermissionManager
from reze.ui import ascii

_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


class CommandContext:
    """Everything a command handler needs for one invocation."""

    def __init__(
        self,
        message: Any,
        client: Any,
        command_name: str,
        args: List[str],
        raw_text: str,
        command: Optional["Command"] = None,
    ):
        self.message = message
        self.client = client
        self.command_name = command_name
        self.command = command
        self.args = args
        self.raw_text = raw_text
        self.chat_id = getattr(message, "chat_id", None)
        self.sender_id = getattr(message, "sender_id", None)
        self.is_reply = bool(getattr(message, "reply_to_msg_id", None))
        self.started_at = time.time()

    # ------------------------------------------------------------------ helpers
    @property
    def args_text(self) -> str:
        return " ".join(self.args)

    @property
    def is_owner(self) -> bool:
        return PermissionManager.is_owner(getattr(self, "sender_id", 0) or 0)

    @property
    def usage(self) -> str:
        return (self.command.usage if self.command else "") or f".{self.command_name}"

    async def _send(self, text: str):
        """Deliver one chunk, preferring an inline reply."""
        if hasattr(self.message, "reply"):
            try:
                return await self.message.reply(text)
            except Exception as exc:  # message deleted, permissions, FloodWait...
                logger.debug("Inline reply failed (%s); falling back to send_message.", exc)
        if hasattr(self.client, "send_message") and self.chat_id:
            return await self.client.send_message(self.chat_id, text)
        if hasattr(self.message, "edit"):
            return await self.message.edit(text)
        return text

    async def reply(self, text: Any = ""):
        """Reply, splitting long output into Telegram-safe messages."""
        chunks = ascii.split_text(str(text))
        if not chunks:
            return None
        first = None
        for index, chunk in enumerate(chunks):
            try:
                result = await self._send(chunk)
            except Exception as exc:  # never raise from a delivery failure
                logger.error("Could not deliver a response chunk: %s", exc)
                return first
            if index == 0:
                first = result
        return first

    async def reply_usage(self, note: str = "") -> Any:
        """Render a usage hint for the current command."""
        body = [f"Usage: {self.usage}"]
        if note:
            body.append(note)
        return await self.reply(ascii.warning("Invalid arguments", body))

    async def reply_error(self, message: str, detail: str = "") -> Any:
        body = [message]
        if detail:
            body.append(detail)
        return await self.reply(ascii.error("Command failed", body))

    async def edit_or_reply(self, text: Any):
        """Edit the command message when possible (used for progress updates)."""
        if hasattr(self.message, "edit"):
            try:
                return await self.message.edit(str(text))
            except Exception:
                pass
        return await self.reply(text)

    async def send_file(self, file: Any = None, **kwargs):
        """Send media through the authenticated client.

        Telethon's signature is ``send_file(entity, file, *, ...)``: the chat must be
        passed as the first positional argument (there is no ``chat_id`` keyword).
        """
        if not hasattr(self.client, "send_file"):
            raise CommandExecutionError("Media delivery is unavailable: no Telegram client.")
        entity = kwargs.pop("entity", None) or kwargs.pop("chat_id", None) or self.chat_id
        kwargs.pop("chat_id", None)
        if file is None:
            raise CommandExecutionError("send_file() needs a file to send.")
        return await self.client.send_file(entity, file, **kwargs)

    async def delete(self) -> None:
        if hasattr(self.message, "delete"):
            try:
                await self.message.delete()
            except Exception as exc:
                logger.debug("Could not delete the command message: %s", exc)

    async def get_reply_message(self) -> Any:
        if hasattr(self.message, "get_reply_message"):
            return await self.message.get_reply_message()
        return None

    async def get_target_user_id(self) -> Optional[int]:
        """Resolve a target user from a reply or from the first argument."""
        if self.is_reply:
            if hasattr(self.message, "get_reply_message"):
                reply_msg = await self.message.get_reply_message()
                if reply_msg and getattr(reply_msg, "sender_id", None):
                    return reply_msg.sender_id
            elif hasattr(self.message, "reply_to_user_id"):
                return self.message.reply_to_user_id
        if self.args:
            arg = self.args[0]
            if arg.lstrip("-").isdigit():
                return int(arg)
        return None


class Command:
    """A registered command and all of its metadata."""

    __slots__ = (
        "name",
        "handler",
        "category",
        "description",
        "usage",
        "aliases",
        "owner_only",
        "admin_only",
        "group_only",
        "cooldown",
        "permissions",
        "plugin",
        "examples",
    )

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
        group_only: bool = False,
        cooldown: int = 0,
        permissions: Iterable[str] = (),
        plugin: Optional[str] = None,
        examples: Iterable[str] = (),
    ):
        self.name = name.lower()
        self.handler = handler
        self.category = category
        self.description = description
        self.usage = usage or f".{name}"
        self.aliases = [alias.lower() for alias in (aliases or [])]
        self.owner_only = owner_only
        self.admin_only = admin_only
        self.group_only = group_only
        self.cooldown = max(0, int(cooldown or 0))
        self.permissions = tuple(permissions)
        self.plugin = plugin
        self.examples = tuple(examples)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "usage": self.usage,
            "aliases": list(self.aliases),
            "owner_only": self.owner_only,
            "admin_only": self.admin_only,
            "group_only": self.group_only,
            "cooldown": self.cooldown,
            "permissions": list(self.permissions),
            "plugin": self.plugin,
        }


class CommandRouter:
    def __init__(self, default_prefix: str = "."):
        self.prefix = default_prefix or "."
        self.commands: Dict[str, Command] = {}
        self.aliases_map: Dict[str, str] = {}
        self.total_executed = 0
        self.errors_count = 0
        self.denied_count = 0
        self.start_time = time.time()
        self.last_error = ""
        self._cooldowns: Dict[Tuple[str, int], float] = {}

    # ------------------------------------------------------------- registration
    def register(
        self,
        name: str,
        category: str = "General",
        description: str = "",
        usage: str = "",
        aliases: Optional[List[str]] = None,
        owner_only: bool = False,
        admin_only: bool = False,
        group_only: bool = False,
        cooldown: int = 0,
        permissions: Iterable[str] = (),
        plugin: Optional[str] = None,
        replace: bool = False,
        examples: Iterable[str] = (),
    ):
        """Decorator that registers a command handler."""
        command_name = (name or "").strip().lower()
        if not _NAME_RE.match(command_name):
            raise CommandExecutionError(
                f"Invalid command name '{name}': use 1-32 lowercase letters, digits or underscores."
            )

        def decorator(handler: Callable):
            existing = self.commands.get(command_name)
            if existing is not None:
                if not replace:
                    owner = existing.plugin or "core"
                    raise DuplicateCommandError(
                        f"Command '.{command_name}' is already registered by {owner}."
                    )
                self.unregister(command_name)

            for alias in aliases or []:
                alias_lower = alias.strip().lower()
                current = self.aliases_map.get(alias_lower, alias_lower)
                if current in self.commands and not replace:
                    raise DuplicateCommandError(
                        f"Alias '{alias_lower}' conflicts with the command '.{current}'."
                    )

            command = Command(
                name=command_name,
                handler=handler,
                category=category,
                description=description,
                usage=usage,
                aliases=aliases,
                owner_only=owner_only,
                admin_only=admin_only,
                group_only=group_only,
                cooldown=cooldown,
                permissions=permissions,
                plugin=plugin,
                examples=examples,
            )
            self.commands[command.name] = command
            for alias in command.aliases:
                self.aliases_map[alias] = command.name
            return handler

        return decorator

    def unregister(self, name: str, plugin: Optional[str] = None) -> bool:
        """Remove a command and its aliases. Plugin-scoped removal is safer."""
        command = self.commands.get((name or "").lower())
        if command is None:
            return False
        if plugin is not None and command.plugin != plugin:
            return False
        self.commands.pop(command.name, None)
        for alias in command.aliases:
            if self.aliases_map.get(alias) == command.name:
                self.aliases_map.pop(alias, None)
        return True

    # ---------------------------------------------------------------- inspection
    def resolve(self, trigger: str) -> Optional[Command]:
        name = (trigger or "").lower()
        return self.commands.get(self.aliases_map.get(name, name))

    def categories(self) -> Dict[str, List[Command]]:
        grouped: Dict[str, List[Command]] = {}
        for command in self.commands.values():
            grouped.setdefault(command.category, []).append(command)
        for commands in grouped.values():
            commands.sort(key=lambda c: c.name)
        return dict(sorted(grouped.items()))

    def search(self, query: str) -> List[Command]:
        needle = (query or "").lower()
        matches = []
        for command in self.commands.values():
            haystack = " ".join(
                [command.name, command.description, command.category, " ".join(command.aliases)]
            ).lower()
            if needle in haystack:
                matches.append(command)
        return sorted(matches, key=lambda c: c.name)

    def command_names(self) -> List[str]:
        return sorted(self.commands)

    # ---------------------------------------------------------------- execution
    def _cooldown_remaining(self, command: Command, sender_id: int) -> int:
        if command.cooldown <= 0:
            return 0
        key = (command.name, int(sender_id or 0))
        last = self._cooldowns.get(key, 0.0)
        remaining = command.cooldown - (time.time() - last)
        if remaining <= 0:
            self._cooldowns[key] = time.time()
            return 0
        return int(remaining) + 1

    def _prune_cooldowns(self) -> None:
        if len(self._cooldowns) > 1024:
            cutoff = time.time() - 3600
            self._cooldowns = {k: v for k, v in self._cooldowns.items() if v >= cutoff}

    @staticmethod
    def public_commands_enabled() -> bool:
        """``REZE_PUBLIC_COMMANDS=true`` restores the old behaviour (anyone may run commands)."""
        return os.environ.get("REZE_PUBLIC_COMMANDS", "").strip().lower() in {"1", "true", "yes", "on"}

    def is_authorized(self, message: Any) -> bool:
        """
        Only the account owner may trigger commands.

        Strangers who type ``.something`` in a group must get *no* reaction at all
        (no reply, no error, no "unknown command" hint), otherwise they assume the
        userbot is talking to them. A message counts as the owner's when it is
        outgoing from this account or its sender is ``REZE_OWNER_ID``.
        """
        if self.public_commands_enabled():
            return True
        if getattr(message, "out", False):
            return True
        return PermissionManager.is_owner(getattr(message, "sender_id", 0) or 0)

    async def handle_message(self, message: Any, client: Any) -> Optional[Any]:
        """Parse and execute a dot command if the message contains one."""
        text = getattr(message, "message", None) or getattr(message, "text", "") or ""
        if not text or not text.startswith(self.prefix):
            return None

        if not self.is_authorized(message):
            self.denied_count += 1
            logger.debug("Ignored a command-like message from non-owner %s", getattr(message, "sender_id", None))
            return None

        raw_cmd = text[len(self.prefix):].strip()
        if not raw_cmd:
            return None

        parts = raw_cmd.split()
        trigger = parts[0].lower()
        args = parts[1:]
        command = self.resolve(trigger)
        if command is None:
            return await self._unknown_command(message, client, trigger)

        sender_id = getattr(message, "sender_id", 0) or 0
        chat_id = getattr(message, "chat_id", 0) or 0

        ctx = CommandContext(
            message=message,
            client=client,
            command_name=command.name,
            args=args,
            raw_text=raw_cmd,
            command=command,
        )

        # 1. Owner-only commands are silently ignored for anyone else so the
        #    userbot does not reveal its command surface to strangers.
        if command.owner_only and not PermissionManager.is_owner(sender_id):
            self.denied_count += 1
            logger.warning("Denied .%s for non-owner %s", command.name, sender_id)
            return None

        # 2. Group-admin commands.
        if command.admin_only:
            can_moderate = await PermissionManager.can_moderate(client, chat_id, sender_id)
            if not can_moderate:
                self.denied_count += 1
                return await ctx.reply(
                    ascii.warning("Not allowed", ["You need group admin rights for this command."])
                )

        # 3. Group-only commands.
        is_group = bool(getattr(message, "is_group", False) or (chat_id and chat_id < 0))
        if command.group_only and not is_group:
            return await ctx.reply(ascii.warning("Groups only", ["Run this command inside a group."]))

        # 4. Cooldowns protect Telegram rate limits on expensive commands.
        if sender_id and command.cooldown:
            remaining = self._cooldown_remaining(command, sender_id)
            if remaining:
                return await ctx.reply(
                    ascii.warning("Slow down", [f"Try .{command.name} again in {remaining}s."])
                )
            self._prune_cooldowns()

        try:
            self.total_executed += 1
            logger.info(
                "Executing .%s by %s in chat %s", command.name, sender_id, chat_id
            )
            result = command.handler(ctx)
            if inspect.isawaitable(result):
                result = await result
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - user-visible, logged with traceback
            self.errors_count += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            logger.error("Error executing .%s: %s", command.name, exc, exc_info=True)
            detail = ascii.sanitize(str(exc))[:300]
            return await ctx.reply(
                ascii.error(
                    f".{command.name} failed",
                    [detail] if detail else ["The command raised an unexpected error."],
                )
            )

    async def _unknown_command(self, message: Any, client: Any, trigger: str):
        """Tell a user about a typo without leaking the full command list."""
        chat_id = getattr(message, "chat_id", 0)
        hint = ascii.warning(
            "Unknown command",
            [
                f"'.{trigger}' is not a registered command.",
                f"Run {self.prefix}help to list available commands.",
            ],
        )
        try:
            if hasattr(message, "reply"):
                return await message.reply(hint)
            if hasattr(client, "send_message") and chat_id:
                return await client.send_message(chat_id, hint)
        except Exception as exc:
            logger.debug("Could not answer an unknown command: %s", exc)
        return None


router = CommandRouter(default_prefix=settings.default_prefix)
