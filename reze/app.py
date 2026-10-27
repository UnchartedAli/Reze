"""
Reze Main Application Entry Point.

Coordinates the Telegram MTProto userbot client, the command router, the clock
scheduler, and the web control panel. The process is designed to stay healthy
on both a VPS and managed PaaS platforms (Render, Railway, Koyeb, Fly.io, ...):

* binds the panel to the platform ``PORT`` on ``0.0.0.0``;
* exposes ``/healthz`` for platform health checks;
* keeps the web panel alive even when Telegram is not configured/logged in;
* reconnects the MTProto client with exponential backoff;
* shuts down cleanly on ``SIGTERM`` (the signal PaaS platforms send).

Developed by UnchartedAli — https://t.me/yamods
"""

import asyncio
import signal
import sys
import threading

from reze import __author__, __channel__, __channel_url__, __version__
from reze.config import settings
from reze.logging_config import logger, setup_logging
from reze.command_router import router
from reze.telegram_client import telegram_manager, events
from reze.scheduler import clock_scheduler
from reze.plugin_manager import plugin_manager
from reze.web.app import run_web_server, stop_web_server

# Import all command suites to register them with the router
import reze.commands.general
import reze.commands.profile
import reze.commands.admin
import reze.commands.moderation
import reze.commands.security
import reze.commands.privacy
import reze.commands.plugins

# Import modules
from reze.modules.antiflood import antiflood_tracker
from reze.modules.filters import check_message_filters, check_blacklists


BANNER = r"""
==============================================================
        REZE - TELEGRAM USERBOT & WEB CONTROL PANEL
        Developer : UnchartedAli
        Channel   : @yamods
        Panel     : MTProto Userbot + Web Control Panel
==============================================================
"""


async def handle_incoming_telegram_message(event):
    """Global message handler for commands, filters, and flood prevention."""
    message = event.message
    chat_id = event.chat_id
    sender_id = event.sender_id
    text = getattr(message, "text", "")

    # 1. Check AntiFlood (only in groups and for non-owners)
    if chat_id and chat_id < 0 and sender_id != settings.owner_id:
        is_flood, action = antiflood_tracker.record_and_check(chat_id, sender_id)
        if is_flood:
            logger.warning("AntiFlood triggered for user %d in chat %d! Action: %s", sender_id, chat_id, action)
            try:
                if action == "mute" and hasattr(event.client, "edit_permissions"):
                    from telethon.tl.types import ChatBannedRights
                    await event.client.edit_permissions(chat_id, sender_id, ChatBannedRights(send_messages=True))
                    await event.reply("🚨 کاربر گرامی، به علت ارسال سریع پیام‌ها موقتاً بی‌صدا شدید.")
                elif action == "kick" and hasattr(event.client, "kick_participant"):
                    await event.client.kick_participant(chat_id, sender_id)
            except Exception as e:
                logger.error("Failed to execute antiflood action: %s", e)
            return

    # 2. Check Blacklists
    if chat_id and chat_id < 0 and text:
        bl_match = check_blacklists(chat_id, text)
        if bl_match:
            trigger_word, bl_action = bl_match
            logger.info("Blacklist word '%s' detected in chat %d", trigger_word, chat_id)
            try:
                await message.delete()
            except Exception:
                pass
            return

    # 3. Process Dot Commands
    if text and text.startswith(router.prefix):
        await router.handle_message(message, event.client)
        return

    # 4. Check Group Auto-Reply Filters
    if chat_id and text:
        reply_filter = check_message_filters(chat_id, text)
        if reply_filter:
            await event.reply(reply_filter)


def start_web_server_thread():
    """Run the Web Panel in a dedicated background daemon thread."""
    server_thread = threading.Thread(
        target=run_web_server,
        kwargs={"host": settings.effective_web_host, "port": settings.web_port},
        daemon=True,
        name="reze-web-panel",
    )
    server_thread.start()
    return server_thread


def _stdin_is_tty() -> bool:
    """True only when an interactive terminal is available safely."""
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except (OSError, ValueError):
        return False


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Gracefully handle SIGTERM/SIGINT on Linux/macOS (PaaS and VPS)."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows has no asyncio signal-handler support; Ctrl+C is handled
            # by the KeyboardInterrupt path in __main__ instead.
            continue


async def _telegram_reconnect_loop() -> None:
    """Keep the MTProto connection alive with exponential backoff."""
    delay = 5
    while True:
        try:
            await telegram_manager.client.run_until_disconnected()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Telegram client stopped unexpectedly: %s", exc)

        if not telegram_manager.client:
            return

        logger.warning("Telegram disconnected. Reconnecting in %d seconds...", delay)
        await asyncio.sleep(delay)

        if await telegram_manager.start():
            delay = 5
            logger.info("Telegram connection restored.")
        else:
            delay = min(delay * 2, 300)


async def main():
    """Main async bootstrap function."""
    setup_logging(settings.log_level)
    print(BANNER)
    print(f"    Version {__version__}  |  {__author__}  |  {__channel__}\n")

    logger.info("Starting Reze Userbot v%s by %s (%s)", __version__, __author__, __channel__)
    logger.info(
        "Platform: %s | hosted: %s | panel bind: %s:%d | data dir: %s",
        settings.platform_name,
        settings.is_hosted,
        settings.effective_web_host,
        settings.web_port,
        settings.data_dir,
    )

    # Discover and load custom plugins
    plugin_manager.discover_and_load_all()

    # Start the Web Control Panel first so platform health checks pass quickly.
    start_web_server_thread()
    panel_url = settings.display_url
    logger.info("Web panel: %s | health: %s", panel_url, settings.healthcheck_path)

    # Start Profile Clock Scheduler
    clock_scheduler.client_wrapper = telegram_manager
    clock_scheduler.start()

    # Validate configuration (non-fatal: the panel is useful for diagnostics).
    for message in settings.validate_production():
        logger.warning("Configuration: %s", message)
    for note in settings.deployment_notes():
        logger.warning("Deployment note: %s", note)

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    telegram_task = None
    connected = await telegram_manager.start()

    # On a VPS/local terminal we can perform the one-time phone/code login.
    # PaaS platforms have no TTY: use scripts/generate_session.py there.
    if (
        not connected
        and telegram_manager.client
        and not settings.session_string
        and _stdin_is_tty()
    ):
        logger.info("No authorized session found. Starting one-time Telegram login...")
        connected = await telegram_manager.login_interactive()

    if connected and telegram_manager.client and events:
        telegram_manager.client.add_event_handler(
            handle_incoming_telegram_message,
            events.NewMessage(),
        )
        logger.info("Registered MTProto NewMessage handler. Listening for commands...")
        telegram_task = asyncio.create_task(_telegram_reconnect_loop())
    else:
        logger.warning(
            "Reze is running in panel-only mode. Open the web panel, finish the "
            "configuration and provide REZE_SESSION_STRING to enable the userbot."
        )
        logger.info("Health endpoint: %s", settings.healthcheck_path)

    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down Reze cleanly...")
        clock_scheduler.stop()
        stop_web_server()

        if telegram_task:
            telegram_task.cancel()
            try:
                await telegram_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        try:
            await asyncio.wait_for(telegram_manager.disconnect(), timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception:
            pass

        logger.info("Reze stopped. Thanks for using Reze - %s (%s)", __author__, __channel_url__)


if __name__ == "__main__":
    # Telethon behaves best with the selector loop on Windows.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Terminating Reze cleanly...")
    except Exception:
        logger.exception("Fatal error during startup")
        sys.exit(1)
