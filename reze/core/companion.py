"""
Optional Telegram Bot Companion (owner-only settings menu).

The companion is a *separate* Bot API bot that can show and toggle REZE options
from a phone. It is OFF by default, starts only when ``bot_companion`` is
enabled, and answers only the configured owner. Sensitive features cannot be
enabled from a button: they still require the typed ``confirm`` word.

The bot token is read from ``REZE_COMPANION_TOKEN`` and is never logged. No
prompts, secrets or message bodies are sent to the bot's chat.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from reze.config import settings
from reze.core.registry import Service
from reze.features import FeatureConfirmationRequired, feature_spec, features
from reze.localization import LANGUAGES, get_language, set_language
from reze.logging_config import logger

API_ROOT = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 3900


class CompanionService(Service):
    name = "companion"
    feature = "bot_companion"
    description = "Owner-only Telegram bot with an inline settings menu."

    def __init__(self) -> None:
        super().__init__()
        self._offset = 0

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def configured() -> bool:
        return bool(settings.companion_token.strip() and settings.owner_id)

    def _api(self, method: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
        token = settings.companion_token.strip()
        if not token:
            raise RuntimeError("REZE_COMPANION_TOKEN is not configured.")
        data = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            API_ROOT.format(token=token, method=method),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Bot API HTTP {exc.code} for {method}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise RuntimeError(f"Bot API request failed ({method}): {type(exc).__name__}") from exc
        if not body.get("ok"):
            raise RuntimeError(f"Bot API rejected {method}")
        return body.get("result") or {}

    async def _call(self, method: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 30):
        return await asyncio.to_thread(self._api, method, payload, timeout)

    def _is_owner(self, update: Dict[str, Any]) -> bool:
        message = update.get("message") or update.get("edited_message") or {}
        callback = update.get("callback_query") or {}
        user = message.get("from") or callback.get("from") or {}
        return bool(user.get("id")) and int(user["id"]) == int(settings.owner_id)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if not self.configured():
            self.status = "failed"
            self.error = "REZE_COMPANION_TOKEN and REZE_OWNER_ID are required."
            logger.warning("Companion not started: token or owner id missing.")
            return
        await super().start()
        self._spawn(self._loop(), "companion")
        logger.info("Bot companion started (owner-only, long polling).")

    async def _loop(self) -> None:
        delay = 2
        while self.status == "running":
            try:
                updates = await self._call(
                    "getUpdates",
                    {"offset": self._offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]},
                    timeout=40,
                )
                delay = 2
                for update in updates or []:
                    self._offset = max(self._offset, int(update.get("update_id") or 0) + 1)
                    try:
                        await self.handle_update(update)
                    except Exception as exc:  # noqa: BLE001 - one update cannot stop the bot
                        logger.debug("Companion update failed: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - network outages are expected
                logger.warning("Companion polling error: %s", exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    # ------------------------------------------------------------------ handling
    async def handle_update(self, update: Dict[str, Any]) -> None:
        if not self._is_owner(update):
            return
        callback = update.get("callback_query")
        if callback:
            await self._on_callback(callback)
            return
        message = update.get("message") or {}
        text = str(message.get("text") or "").strip()
        chat_id = (message.get("chat") or {}).get("id")
        if not chat_id or not text:
            return
        await self._on_command(int(chat_id), text)

    async def _on_callback(self, callback: Dict[str, Any]) -> None:
        data = str(callback.get("data") or "")
        callback_id = str(callback.get("id") or "")
        message = callback.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        answer = "Unknown action."
        if data.startswith("toggle:") and chat_id:
            key = data.split(":", 1)[1]
            try:
                spec = feature_spec(key)
                if features.is_enabled(key):
                    features.disable(key, actor=settings.owner_id)
                    answer = f"{spec.key} is now OFF."
                elif spec.sensitive:
                    answer = f"Sensitive: send /enable {spec.key} confirm"
                else:
                    features.enable(key, actor=settings.owner_id, confirmed=True)
                    answer = f"{spec.key} is now ON."
            except (KeyError, FeatureConfirmationRequired) as exc:
                answer = str(exc)[:180]
            await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": answer})
            await self._send_menu(int(chat_id), prefix=answer)
            return
        await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": answer})

    async def _on_command(self, chat_id: int, text: str) -> None:
        parts = text.split()
        command = parts[0].split("@")[0].lower()
        args = parts[1:]

        if command in {"/start", "/help", "/features", "/menu"}:
            await self._send_menu(chat_id)
            return

        if command in {"/enable", "/disable"}:
            if not args:
                await self._send(chat_id, "Usage: /enable <key> [confirm] or /disable <key>")
                return
            key = args[0].lower()
            try:
                spec = feature_spec(key)
            except KeyError:
                await self._send(chat_id, f"Unknown feature: {key}")
                return
            if command == "/disable":
                features.disable(key, actor=settings.owner_id)
                await self._send(chat_id, f"{spec.label} ({key}) is now OFF.")
            else:
                confirmed = "confirm" in {value.lower() for value in args[1:]}
                try:
                    features.enable(key, actor=settings.owner_id, confirmed=confirmed)
                except FeatureConfirmationRequired:
                    await self._send(chat_id, f"Sensitive feature. Send: /enable {key} confirm")
                    return
                await self._send(chat_id, f"{spec.label} ({key}) is now ON.")
            await self._send_menu(chat_id)
            return

        if command == "/language":
            if not args:
                await self._send(chat_id, f"Language: {get_language()}. Use /language en or /language fa")
                return
            try:
                code = set_language(args[0])
            except ValueError as exc:
                await self._send(chat_id, str(exc))
                return
            await self._send(chat_id, f"Language: {LANGUAGES.get(code, code)} ({code})")
            return

        if command == "/status":
            summary = features.summary()
            await self._send(
                chat_id,
                f"REZE companion\nFeatures ON: {summary['enabled']}/{summary['total']}\n"
                f"Language: {get_language()}\nUse /features for the menu.",
            )
            return

        await self._send(chat_id, "Commands: /features /enable <key> [confirm] /disable <key> /language /status")

    # --------------------------------------------------------------------- send
    async def _send(self, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": (text or "")[:MAX_TEXT], "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            await self._call("sendMessage", payload)
        except Exception as exc:  # noqa: BLE001 - delivery failure is logged without contents
            logger.warning("Companion could not send a message: %s", exc)

    @staticmethod
    def _keyboard() -> Dict[str, Any]:
        rows: List[List[Dict[str, str]]] = []
        row: List[Dict[str, str]] = []
        for spec in _feature_list():
            state = "ON" if features.is_enabled(spec.key) else "OFF"
            row.append({"text": f"[{state}] {spec.key}", "callback_data": f"toggle:{spec.key}"})
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return {"inline_keyboard": rows}

    async def _send_menu(self, chat_id: int, prefix: str = "") -> None:
        summary = features.summary()
        lines = [
            "REZE settings (optional features start OFF).",
            f"ON: {summary['enabled']}/{summary['total']} · Language: {get_language()}",
            "Tap a non-sensitive feature to toggle it. Sensitive features need:",
            "/enable <key> confirm",
            "Nothing below changes until you tap or type.",
        ]
        if prefix:
            lines.insert(0, prefix)
        await self._send(chat_id, "\n".join(lines), reply_markup=self._keyboard())


def _feature_list():
    from reze.features import FEATURES

    return FEATURES


companion_service = CompanionService()

__all__ = ["CompanionService", "companion_service"]
