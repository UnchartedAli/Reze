"""Shared background infrastructure for Reze."""

from reze.core.confirmations import Confirmation, ConfirmationStore, confirmations
from reze.core.presence import PresenceService, presence_service
from reze.core.tasks import TaskManager, TaskRecord, TaskStatus, task_manager

__all__ = [
    "Confirmation",
    "ConfirmationStore",
    "PresenceService",
    "TaskManager",
    "TaskRecord",
    "TaskStatus",
    "confirmations",
    "presence_service",
    "task_manager",
]
