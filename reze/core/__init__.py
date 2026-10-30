"""Shared background infrastructure for Reze.

The exports are resolved lazily (PEP 562) because ``reze.database`` imports
``reze.core.migrations`` while the database module itself is still being
initialised. Eagerly importing the background services here would create a
circular import (``database -> core -> presence -> preferences -> database``).
"""

from typing import Any

_LAZY = {
    "Confirmation": ("reze.core.confirmations", "Confirmation"),
    "ConfirmationStore": ("reze.core.confirmations", "ConfirmationStore"),
    "confirmations": ("reze.core.confirmations", "confirmations"),
    "PresenceService": ("reze.core.presence", "PresenceService"),
    "presence_service": ("reze.core.presence", "presence_service"),
    "TaskManager": ("reze.core.tasks", "TaskManager"),
    "TaskRecord": ("reze.core.tasks", "TaskRecord"),
    "TaskStatus": ("reze.core.tasks", "TaskStatus"),
    "task_manager": ("reze.core.tasks", "task_manager"),
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _LAZY[name]
    except KeyError as exc:
        raise AttributeError(f"module 'reze.core' has no attribute '{name}'") from exc
    from importlib import import_module

    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(globals()) + __all__)
