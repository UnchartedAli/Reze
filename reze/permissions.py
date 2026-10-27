"""
Permission control system for Reze.
Guarantees that sensitive and administrative commands cannot be executed by unauthorized users.
"""

from typing import Optional, Any
from reze.config import settings
from reze.logging_config import logger

class PermissionManager:
    @staticmethod
    def is_owner(user_id: int) -> bool:
        """Check if user_id matches the configured bot owner."""
        return bool(settings.owner_id and user_id == settings.owner_id)

    @staticmethod
    async def can_moderate(client: Any, chat_id: int, user_id: int) -> bool:
        """
        Check if user_id has admin/moderation permissions in the group.
        Always grants to bot owner.
        """
        if PermissionManager.is_owner(user_id):
            return True
            
        try:
            # If client provides get_permissions / get_participant
            if hasattr(client, "get_permissions"):
                perms = await client.get_permissions(chat_id, user_id)
                return getattr(perms, "is_admin", False)
            return False
        except Exception as e:
            logger.warning("Permission check failed for user %d in chat %d: %s", user_id, chat_id, e)
            return False

    @staticmethod
    async def bot_has_admin_rights(client: Any, chat_id: int) -> bool:
        """Verify the userbot has the necessary rights in the chat to perform admin actions."""
        try:
            if hasattr(client, "get_permissions"):
                me = await client.get_me()
                perms = await client.get_permissions(chat_id, me.id)
                return getattr(perms, "is_admin", False)
            return True
        except Exception:
            return True
