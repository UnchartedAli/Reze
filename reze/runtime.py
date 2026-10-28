"""
Runtime hooks shared by the async bot and the threaded web panel.

The panel runs in its own thread, so it cannot touch asyncio primitives
directly. The application registers its event loop here at startup and the web
layer submits coroutines through :func:`run_coroutine`.
"""

import asyncio
import concurrent.futures
from typing import Any, Coroutine, Optional

_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    return _MAIN_LOOP


def run_coroutine(coro: Coroutine[Any, Any, Any], timeout: float = 15.0) -> Any:
    """Run a coroutine on the bot's event loop from another thread."""
    loop = _MAIN_LOOP
    if loop is None or loop.is_closed():
        raise RuntimeError("The Reze event loop is not available.")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)
