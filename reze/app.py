"""
Reze application entry point.

Wires together the Telegram MTProto client, the command router, plugins, the
media/AI/automation services and the web control panel. The process is designed
to stay healthy on a VPS and on managed platforms:

* the panel binds to ``PORT``/``REZE_WEB_PORT`` and exposes ``/healthz``;
* the panel keeps running when Telegram is not configured;
* the MTProto connection reconnects with exponential backoff;
* every background service is stopped on ``SIGTERM``/``SIGINT``.
"""

import asyncio
import signal
import sys
import threading

from reze import __author__, __channel__, __channel_url__, __version__
from reze.automation.engine import automation_engine
from reze.command_router import router
from reze.config import settings
from reze.core.companion import companion_service
from reze.core.presence import presence_service
from reze.core.registry import registry
from reze.features import features
from reze.logging_config import logger, setup_logging
from reze.personal.focus import focus_service
from reze.plugin_manager import plugin_manager
from reze.preferences import get_pref
from reze.productivity.reminders import reminder_service
from reze.runtime import set_main_loop
from reze.scheduler import clock_scheduler
from reze.automation.workflow import workflow_service
from reze.capture.inbox import inbox_service
from reze.modules.reactions import random_reaction_service
from reze.telegram_client import events, telegram_manager
from reze.ui import ascii
from reze.web.app import run_web_server, stop_web_server

# Command suites register themselves with the router on import.
import reze.commands.general  # noqa: F401
import reze.commands.profile  # noqa: F401
import reze.commands.admin  # noqa: F401
import reze.commands.moderation  # noqa: F401
import reze.commands.security  # noqa: F401
import reze.commands.privacy  # noqa: F401
import reze.commands.plugins  # noqa: F401
import reze.commands.appearance  # noqa: F401
import reze.commands.media  # noqa: F401
import reze.commands.ai  # noqa: F401
import reze.commands.productivity  # noqa: F401
import reze.commands.automation  # noqa: F401
import reze.commands.system  # noqa: F401
import reze.commands.presence  # noqa: F401
import reze.commands.watch  # noqa: F401
import reze.commands.afk  # noqa: F401
import reze.commands.alerts  # noqa: F401
import reze.commands.owner  # noqa: F401
import reze.commands.groupadmin  # noqa: F401
import reze.commands.fun  # noqa: F401
import reze.commands.tools  # noqa: F401
import reze.commands.downloads  # noqa: F401
import reze.commands.features  # noqa: F401
import reze.commands.language  # noqa: F401
import reze.commands.knowledge  # noqa: F401
import reze.commands.crm  # noqa: F401
import reze.commands.decisions  # noqa: F401
import reze.commands.focus  # noqa: F401
import reze.commands.projects  # noqa: F401
import reze.commands.expenses  # noqa: F401
import reze.commands.writing  # noqa: F401
import reze.commands.insights  # noqa: F401
import reze.commands.capture  # noqa: F401
import reze.commands.vault  # noqa: F401
import reze.commands.maintenance  # noqa: F401
import reze.commands.workflows  # noqa: F401
import reze.commands.agent  # noqa: F401
import reze.commands.companion  # noqa: F401
import reze.commands.reactions  # noqa: F401

from reze.modules.antiflood import antiflood_tracker
from reze.modules.filters import check_blacklists, check_message_filters
from reze.games.tictactoe import tictactoe_manager
from reze.modules.afk import afk_service
from reze.modules.alerts import alert_service
from reze.modules.msglog import message_logger


async def handle_incoming_telegram_message(event):
    """Global message handler: moderation hooks, commands, filters, automation."""
    message = event.message
    chat_id = event.chat_id
    sender_id = event.sender_id
    text = getattr(message, "text", "") or ""

    # 0. Message Guard: keep a local copy so deleted/edited messages can be recovered.
    try:
        await message_logger.on_new_message(event)
    except Exception as exc:  # noqa: BLE001 - logging must never break the bot
        logger.debug("Message Guard capture failed: %s", exc)

    # 0a. Optional Smart Inbox classification. It only records what arrived and
    #     never replies, forwards or contacts anyone.
    if text and not getattr(message, "out", False) and features.is_enabled("smart_inbox"):
        try:
            inbox_service.capture(
                chat_id or 0,
                getattr(message, "id", 0) or 0,
                sender_id or 0,
                text=text,
            )
        except Exception as exc:  # noqa: BLE001 - capture must not break the bot
            logger.debug("Smart Inbox capture failed: %s", exc)

    # 0a2. Optional random reactions (OFF by default, rare, bounded by the service).
    if features.is_enabled("random_reactions"):
        try:
            await random_reaction_service.on_new_message(event)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Random reaction hook failed: %s", exc)

    # 0b. AFK auto-replies / missed-message log, and mention & keyword alerts.
    for hook in (afk_service.on_new_message, afk_service.on_outgoing, alert_service.on_new_message):
        try:
            await hook(event)
        except Exception as exc:  # noqa: BLE001 - these helpers must never break the bot
            logger.debug("Message hook %s failed: %s", getattr(hook, "__qualname__", hook), exc)

    # 0b. Tic-tac-toe moves (plain digits 1-9 from the player whose turn it is).
    try:
        await tictactoe_manager.on_message(event)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Tic-tac-toe hook failed: %s", exc)

    # 1. Anti-flood (groups only, never for the owner).
    if chat_id and chat_id < 0 and sender_id != settings.owner_id:
        is_flood, action = antiflood_tracker.record_and_check(chat_id, sender_id)
        if is_flood:
            logger.warning(
                "Anti-flood triggered for %s in %s (action: %s)", sender_id, chat_id, action
            )
            try:
                if action == "mute" and hasattr(event.client, "edit_permissions"):
                    from telethon.tl.types import ChatBannedRights

                    await event.client.edit_permissions(
                        chat_id, sender_id, ChatBannedRights(send_messages=True)
                    )
                    await event.reply(
                        ascii.warning("Slow down", ["You were muted temporarily for spamming."])
                    )
                elif action == "kick" and hasattr(event.client, "kick_participant"):
                    await event.client.kick_participant(chat_id, sender_id)
            except Exception as exc:  # noqa: BLE001 - moderation must not crash the loop
                logger.error("Anti-flood action failed: %s", exc)
            return

    # 2. Blacklisted words.
    if chat_id and chat_id < 0 and text:
        match = check_blacklists(chat_id, text)
        if match:
            trigger, _action = match
            logger.info("Blacklisted word '%s' detected in %s", trigger, chat_id)
            try:
                await message.delete()
            except Exception:
                pass
            return

    # 3. Dot commands.
    if text and text.startswith(router.prefix) and router.is_authorized(message):
        try:
            await router.handle_message(message, event.client)
        except Exception as exc:  # noqa: BLE001 - router already replies to users
            logger.error("Command dispatch failed: %s", exc)
        return

    # 4. Group auto-reply filters.
    if chat_id and text:
        reply_filter = check_message_filters(chat_id, text)
        if reply_filter:
            try:
                await event.reply(reply_filter)
            except Exception as exc:
                logger.debug("Filter reply failed: %s", exc)

    # 5. Keyword automations (outgoing messages are ignored inside the engine).
    if text:
        try:
            await automation_engine.on_message(message, chat_id, sender_id, text)
        except Exception as exc:  # noqa: BLE001
            logger.error("Automation evaluation failed: %s", exc)


async def _on_message_deleted(event):
    try:
        await message_logger.on_deleted(event)
    except Exception as exc:  # noqa: BLE001
        logger.error("Message Guard (delete) failed: %s", exc)


async def _on_message_edited(event):
    try:
        await message_logger.on_edited(event)
    except Exception as exc:  # noqa: BLE001
        logger.error("Message Guard (edit) failed: %s", exc)


def start_web_server_thread():
    """Run the panel in a daemon thread so the event loop stays responsive."""
    thread = threading.Thread(
        target=run_web_server,
        kwargs={"host": settings.effective_web_host, "port": settings.web_port},
        daemon=True,
        name="reze-web-panel",
    )
    thread.start()
    return thread


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except (OSError, ValueError):
        return False


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError, ValueError):
            continue  # Windows: Ctrl+C is handled by the KeyboardInterrupt path


async def _telegram_reconnect_loop() -> None:
    delay = 5
    while True:
        try:
            await telegram_manager.client.run_until_disconnected()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the process alive
            logger.error("Telegram client stopped unexpectedly: %s", exc)

        if not telegram_manager.client:
            return

        logger.warning("Telegram disconnected. Reconnecting in %ds...", delay)
        await asyncio.sleep(delay)
        if await telegram_manager.start():
            delay = 5
            logger.info("Telegram connection restored.")
        else:
            delay = min(delay * 2, 300)


def _configure_console() -> None:
    """Make banner output safe on consoles with a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            continue


def _safe_print(text: str) -> None:
    """Print without crashing when the console cannot encode box-drawing glyphs."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(
            text.encode(encoding, errors="replace").decode(encoding, errors="replace"),
            flush=True,
        )


async def main():
    _configure_console()
    setup_logging(settings.log_level)
    _safe_print(ascii.banner("TERMINAL"))
    _safe_print(f"    REZE {__version__}  |  {__author__}  |  {__channel__}\n")

    logger.info("Starting Reze %s (%s)", __version__, __channel__)
    logger.info(
        "Platform: %s | hosted: %s | panel bind: %s:%d | data dir: %s",
        settings.platform_name,
        settings.is_hosted,
        settings.effective_web_host,
        settings.web_port,
        settings.data_dir,
    )

    set_main_loop(asyncio.get_running_loop())
    router.prefix = get_pref("prefix", settings.default_prefix) or "."

    plugin_manager.load_all()

    start_web_server_thread()
    logger.info("Web panel: %s | health: %s", settings.display_url, settings.healthcheck_path)

    clock_scheduler.client_wrapper = telegram_manager
    clock_scheduler.start()

    reminder_service.client_provider = lambda: telegram_manager.client
    reminder_service.start()

    presence_service.client_provider = lambda: telegram_manager.client
    presence_service.start()

    automation_engine.client_provider = lambda: telegram_manager.client
    automation_engine.start()

    # REZE 3 optional services. Registration does not start anything: start_all
    # only starts services whose feature the owner explicitly enabled.
    for service in (focus_service, workflow_service, random_reaction_service, companion_service):
        registry.register(service)
    workflow_service.client_provider = lambda: telegram_manager.client
    random_reaction_service.client_provider = lambda: telegram_manager.client
    await registry.start_all()
    if registry.started:
        logger.info("Optional services started: %s", ", ".join(registry.started))

    message_logger.client_provider = lambda: telegram_manager.client
    afk_service.client_provider = lambda: telegram_manager.client
    alert_service.client_provider = lambda: telegram_manager.client
    if message_logger.config["enabled"]:
        message_logger.start()

    for problem in settings.validate_production():
        logger.warning("Configuration: %s", problem)
    for note in settings.deployment_notes():
        logger.warning("Deployment note: %s", note)

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    telegram_task = None
    connected = await telegram_manager.start()

    if not connected and telegram_manager.client and not settings.session_string and _stdin_is_tty():
        logger.info("No authorized session found. Starting the one-time Telegram login...")
        connected = await telegram_manager.login_interactive()

    if connected and telegram_manager.client and events:
        telegram_manager.client.add_event_handler(
            handle_incoming_telegram_message, events.NewMessage()
        )
        telegram_manager.client.add_event_handler(_on_message_deleted, events.MessageDeleted())
        telegram_manager.client.add_event_handler(_on_message_edited, events.MessageEdited())
        logger.info("Listening for messages on the MTProto connection.")
        telegram_task = asyncio.create_task(_telegram_reconnect_loop())
        if presence_service.enabled():
            # Apply the stored preference as soon as the account is authorized.
            await presence_service.apply_now()
    else:
        logger.warning(
            "Reze is running in panel-only mode. Finish the configuration and provide "
            "REZE_SESSION_STRING to enable the userbot."
        )

    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down Reze...")
        clock_scheduler.stop()
        reminder_service.stop()
        presence_service.stop()
        automation_engine.stop()
        message_logger.stop()
        try:
            await registry.stop_all()
        except Exception as exc:  # noqa: BLE001 - shutdown must continue
            logger.warning("Could not stop optional services cleanly: %s", exc)
        stop_web_server()

        try:
            from reze.core.tasks import task_manager

            await task_manager.shutdown()
        except Exception:
            pass

        if telegram_task:
            telegram_task.cancel()
            try:
                await telegram_task
            except (asyncio.CancelledError, Exception):
                pass

        try:
            await asyncio.wait_for(telegram_manager.disconnect(), timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception:
            pass

        set_main_loop(None)
        logger.info("Reze stopped. %s (%s)", __author__, __channel_url__)


def cli() -> None:
    """Console entry point (``reze``)."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Terminating Reze.")
    except Exception:
        logger.exception("Fatal error during startup")
        sys.exit(1)


if __name__ == "__main__":
    cli()
