"""
Telegram MTProto client wrapper for Reze.

Handles session management (file **or** Telethon StringSession), login, 2FA,
connection status, optional SOCKS5/HTTP proxy, and event dispatching.

The StringSession backend is what makes Reze deployable on ephemeral PaaS
filesystems (Render, Railway, Koyeb, ...): set ``REZE_SESSION_STRING`` and the
bot starts already authenticated, without an interactive terminal.
"""

import getpass
import os
from typing import Any, Callable, Dict, Optional
from urllib.parse import unquote, urlparse

from reze.config import settings
from reze.logging_config import logger
from reze.exceptions import TelegramAPIError

# In environments without telethon installed (e.g. testing / sandbox without
# internet), we keep a clean mockable interface so the web panel still works.
try:
    from telethon import TelegramClient as BaseTelegramClient, events
    from telethon.sessions import StringSession

    TELETHON_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when telethon is absent
    TELETHON_AVAILABLE = False
    BaseTelegramClient = object
    StringSession = None
    events = None


# Errors that mean the stored session can never work again without a new login.
PERMANENT_AUTH_ERRORS = {
    "AuthKeyUnregisteredError",
    "AuthKeyDuplicatedError",
    "AuthKeyInvalidError",
    "SessionExpiredError",
    "SessionRevokedError",
    "UserDeactivatedError",
    "UserDeactivatedBanError",
    "PhoneNumberBannedError",
}


def _is_permanent_auth_error(exc: BaseException) -> bool:
    return type(exc).__name__ in PERMANENT_AUTH_ERRORS


def _parse_proxy(proxy_url: str) -> Optional[Dict[str, Any]]:
    """Parse ``socks5://user:pass@host:port`` (or http/https) for Telethon."""
    if not proxy_url:
        return None

    candidate = proxy_url if "://" in proxy_url else f"socks5://{proxy_url}"
    parsed = urlparse(candidate)
    scheme = (parsed.scheme or "socks5").lower()
    proxy_type = {
        "socks5": "socks5",
        "socks5h": "socks5",
        "socks4": "socks4",
        "http": "http",
        "https": "http",
    }.get(scheme)

    if not proxy_type or not parsed.hostname:
        logger.warning("Ignoring invalid REZE_PROXY value (expected scheme://host:port).")
        return None

    try:
        proxy_port = int(parsed.port or 0)
    except ValueError:
        logger.warning("Ignoring REZE_PROXY with an invalid port.")
        return None

    if not proxy_port:
        logger.warning("Ignoring invalid REZE_PROXY value (expected scheme://host:port).")
        return None

    return {
        "proxy_type": proxy_type,
        "addr": parsed.hostname,
        "port": proxy_port,
        "username": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "rdns": True,
    }


class RezeTelegramClient:
    def __init__(self):
        self.api_id = settings.api_id
        self.api_hash = settings.api_hash
        self.session_path = settings.session_path
        self.session_string = settings.session_string
        self.client: Optional[Any] = None
        self.is_connected = False
        self.session_backend = settings.session_backend
        self.phone_code_hash: Optional[str] = None
        self.phone_number: Optional[str] = None
        self._event_handlers = []
        self._init_client()

    # ------------------------------------------------------------------ startup
    def _init_client(self):
        # Ensure the session parent directory exists even when using a volume.
        session_dir = os.path.dirname(self.session_path)
        if session_dir:
            try:
                os.makedirs(session_dir, exist_ok=True)
            except OSError as exc:
                logger.warning(
                    "Could not create the session directory %s: %s", session_dir, exc
                )

        if not TELETHON_AVAILABLE:
            logger.warning(
                "Telethon is not installed. The web panel will run, but the "
                "Telegram userbot is disabled."
            )
            self.client = None
            return

        if not self.api_id or not self.api_hash:
            logger.warning(
                "REZE_API_ID / REZE_API_HASH are missing. Telegram client is disabled "
                "until they are configured."
            )
            self.client = None
            return

        try:
            if self.session_string:
                if not StringSession:
                    raise RuntimeError("StringSession is unavailable in this Telethon build.")
                session = StringSession(self.session_string)
                self.session_backend = "string"
            else:
                session = self.session_path
                self.session_backend = "file"

            kwargs: Dict[str, Any] = {
                "connection_retries": 5,
                "retry_delay": 3,
                "auto_reconnect": True,
                "request_retries": 5,
            }
            proxy = _parse_proxy(settings.proxy)
            if proxy:
                kwargs["proxy"] = proxy

            self.client = BaseTelegramClient(
                session,
                self.api_id,
                self.api_hash,
                **kwargs,
            )
            logger.info(
                "Telegram client initialized (session backend: %s, proxy: %s).",
                self.session_backend,
                "enabled" if proxy else "disabled",
            )
        except Exception as exc:
            logger.error("Failed to initialize the Telegram client: %s", exc)
            self.client = None

    # ------------------------------------------------------------------- status
    def status(self) -> Dict[str, Any]:
        return {
            "configured": bool(self.api_id and self.api_hash),
            "connected": bool(self.is_connected),
            "session_backend": self.session_backend,
            "telethon_available": TELETHON_AVAILABLE,
        }

    # ------------------------------------------------------------------ connect
    async def start(self) -> bool:
        """Connect to Telegram and report whether the account is authorized."""
        if not self.client:
            logger.warning(
                "Telegram client is not ready. The web panel keeps running so you "
                "can finish the configuration."
            )
            return False

        try:
            await self.client.connect()

            if not await self.client.is_user_authorized():
                self.is_connected = False
                logger.warning(
                    "Telegram session is not authorized yet. Generate one with "
                    "`python scripts/generate_session.py` and set REZE_SESSION_STRING "
                    "(or log in once on a machine with a terminal)."
                )
                return False

            self.is_connected = True
            logger.info(
                "Connected to Telegram (session backend: %s).", self.session_backend
            )
            self._persist_session_snapshot()

            try:
                me = await self.client.get_me()
                if me:
                    username = f"@{me.username}" if getattr(me, "username", None) else "no username"
                    logger.info(
                        "Logged in as %s (id: %s).",
                        username,
                        getattr(me, "id", "unknown"),
                    )
            except Exception as exc:  # non fatal
                logger.debug("Could not fetch the Telegram account info: %s", exc)

            return True

        except Exception as exc:
            self.is_connected = False
            if _is_permanent_auth_error(exc):
                logger.critical(
                    "Telegram session is no longer valid (%s). Generate a new "
                    "REZE_SESSION_STRING with scripts/generate_session.py.",
                    type(exc).__name__,
                )
            else:
                logger.error("Failed to connect to Telegram: %s", exc)
            return False

    async def reconnect(self) -> bool:
        """Attempt a lightweight reconnect without restarting the process."""
        if not self.client:
            return False
        try:
            if not self.client.is_connected():
                await self.client.connect()
            self.is_connected = await self.client.is_user_authorized()
            if self.is_connected:
                logger.info("Telegram reconnected successfully.")
            return self.is_connected
        except Exception as exc:
            self.is_connected = False
            logger.warning("Telegram reconnect attempt failed: %s", exc)
            return False

    async def login_interactive(self) -> bool:
        """
        One-time phone/code login for a VPS or local machine with a terminal.

        PaaS platforms have no TTY, so use ``scripts/generate_session.py`` and
        ``REZE_SESSION_STRING`` there instead.
        """
        if not self.client:
            return False

        try:
            await self.client.connect()
            if await self.client.is_user_authorized():
                self.is_connected = True
                self._persist_session_snapshot()
                return True

            phone = self.phone_number or settings.phone or input(
                "Telegram phone number in international format (+98912...): "
            ).strip()
            if not phone:
                logger.error("No phone number entered; interactive login aborted.")
                return False

            sent_code = await self.client.send_code_request(phone)
            self.phone_code_hash = sent_code.phone_code_hash
            self.phone_number = phone

            code = input("Telegram verification code: ").strip()
            try:
                await self.client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=self.phone_code_hash,
                )
            except Exception as exc:
                if type(exc).__name__ == "SessionPasswordNeededError":
                    password = getpass.getpass("Two-step verification password: ")
                    await self.client.sign_in(password=password)
                else:
                    raise

            self.is_connected = await self.client.is_user_authorized()
            if self.is_connected:
                logger.info("Interactive Telegram login completed successfully.")
                self._persist_session_snapshot()
            return self.is_connected
        except Exception as exc:
            self.is_connected = False
            logger.error("Interactive Telegram login failed: %s", exc)
            return False

    # -------------------------------------------------------------- interactive
    async def send_code_request(self, phone: str) -> Dict[str, Any]:
        """Request a Telegram verification code (used by the session helper)."""
        if not self.client:
            raise TelegramAPIError("Telethon is not initialized.")
        try:
            sent_code = await self.client.send_code_request(phone)
            self.phone_code_hash = sent_code.phone_code_hash
            self.phone_number = phone
            return {"status": "code_sent", "phone": phone}
        except Exception as exc:
            logger.error("Error sending the code request to %s: %s", phone, exc)
            raise TelegramAPIError(str(exc))

    async def sign_in_with_code(self, code: str, password: Optional[str] = None) -> Dict[str, Any]:
        """Sign in with the received code and optional 2FA password."""
        if not self.client or not self.phone_number or not self.phone_code_hash:
            raise TelegramAPIError("No pending sign-in request found.")

        try:
            await self.client.sign_in(
                phone=self.phone_number,
                code=code,
                phone_code_hash=self.phone_code_hash,
            )
            self.is_connected = True
            self._persist_session_snapshot()
            return {"status": "authenticated"}
        except Exception as exc:
            if "SessionPasswordNeededError" in type(exc).__name__ or "2FA" in str(exc):
                if password:
                    await self.client.sign_in(password=password)
                    self.is_connected = True
                    self._persist_session_snapshot()
                    return {"status": "authenticated"}
                return {"status": "password_needed"}
            logger.error("Sign-in failed: %s", exc)
            raise TelegramAPIError(str(exc))

    # ------------------------------------------------------------------ session
    def export_session_string(self) -> Optional[str]:
        """Return the current session as a portable StringSession."""
        if not self.client or not StringSession:
            return None
        try:
            return StringSession.save(self.client.session)
        except Exception as exc:
            logger.debug("Could not export the StringSession: %s", exc)
            return None

    def _persist_session_snapshot(self) -> None:
        """
        Keep a copy of the current StringSession on disk.

        On PaaS the environment variable cannot be updated automatically, but
        the file can be read from a persistent volume and copied into the
        platform dashboard. The file is written with 0600 permissions.
        """
        if self.session_backend != "string":
            return
        exported = self.export_session_string()
        if not exported:
            return
        try:
            data_dir = settings.data_dir or "data"
            os.makedirs(data_dir, exist_ok=True)
            target = os.path.join(data_dir, "session_string.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(exported)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            logger.info("A copy of the session string was saved to %s.", target)
        except Exception as exc:
            logger.debug("Could not persist the session snapshot: %s", exc)

    # ------------------------------------------------------------------ closing
    async def logout(self):
        """Securely log out and disconnect."""
        if self.client and self.is_connected:
            await self.client.log_out()
            self.is_connected = False
            logger.info("Successfully logged out from the Telegram account.")

    async def disconnect(self):
        """Disconnect the MTProto socket cleanly without terminating the session."""
        if self.client:
            try:
                await self.client.disconnect()
            except Exception as exc:
                logger.debug("Disconnect raised: %s", exc)
            finally:
                self.is_connected = False
                logger.info("Disconnected the MTProto client.")

    # ------------------------------------------------------------------- events
    def add_event_handler(self, callback: Callable, event_type: Any):
        """Register a Telethon event listener."""
        if self.client:
            self.client.add_event_handler(callback, event_type)
        self._event_handlers.append((callback, event_type))


telegram_manager = RezeTelegramClient()
