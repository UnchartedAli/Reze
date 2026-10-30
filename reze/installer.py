#!/usr/bin/env python3
"""
REZE 3.0 terminal installer.

A dependency-light, idempotent wizard that writes a ``.env`` file, checks the
runtime, creates the data directory and (optionally) initialises the database.
It never prints API hashes, session strings, passwords or API keys; the review
screen and the final summary show masked values only.

Run it with ``reze-install`` or ``python -m reze.installer``.
"""

from __future__ import annotations

import argparse
import getpass
import os
import platform
import secrets
import shutil
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

MIN_PYTHON = (3, 11)
ENV_ORDER = [
    "REZE_API_ID",
    "REZE_API_HASH",
    "REZE_SESSION_STRING",
    "REZE_OWNER_ID",
    "REZE_PANEL_USERNAME",
    "REZE_PANEL_PASSWORD",
    "REZE_WEB_HOST",
    "REZE_WEB_PORT",
    "REZE_PUBLIC_URL",
    "REZE_LANGUAGE",
    "REZE_TIMEZONE",
    "REZE_THEME",
    "REZE_DATA_DIR",
    "REZE_RETENTION_DAYS",
    "REZE_AUDIT_RETENTION_DAYS",
    "REZE_AI_PROVIDER",
    "REZE_AI_MODEL",
    "REZE_AI_API_KEY",
    "REZE_AI_BASE_URL",
    "REZE_AI_DAILY_BUDGET_CALLS",
    "REZE_AI_TOOL_MAX_CALLS",
    "REZE_VOICE_MODEL",
    "REZE_VOICE_MAX_MB",
    "REZE_VAULT_KEY",
    "REZE_COMPANION_TOKEN",
    "REZE_COMPANION_POLL_SECONDS",
]
SECRET_KEYS = {
    "REZE_API_HASH",
    "REZE_SESSION_STRING",
    "REZE_PANEL_PASSWORD",
    "REZE_AI_API_KEY",
    "REZE_VAULT_KEY",
    "REZE_COMPANION_TOKEN",
}
LOGO = r"""
  ██████╗ ███████╗███████╗███████╗
  ██╔══██╗██╔════╝╚══███╔╝██╔════╝
  ██████╔╝█████╗    ███╔╝ █████╗
  ██╔══██╗██╔══╝   ███╔╝  ██╔══╝
  ██║  ██║███████╗███████╗███████╗
  ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝
      Your Personal Digital Operating System
"""


class InstallerCancelled(Exception):
    """Raised when the user aborts the wizard."""


# --------------------------------------------------------------------------- UI
def _color(code: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return ""
    return code


BOLD = _color("\033[1m")
DIM = _color("\033[2m")
CYAN = _color("\033[36m")
GREEN = _color("\033[32m")
YELLOW = _color("\033[33m")
RED = _color("\033[31m")
RESET = _color("\033[0m")


def say(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def step(number: int, total: int, title: str) -> None:
    say("")
    say(f"{CYAN}[{number}/{total}]{RESET} {BOLD}{title}{RESET}")
    say(f"{DIM}{'-' * 58}{RESET}")


def ok(text: str) -> None:
    say(f"  {GREEN}OK{RESET}   {text}")


def warn(text: str) -> None:
    say(f"  {YELLOW}WARN{RESET} {text}")


def fail(text: str) -> None:
    say(f"  {RED}FAIL{RESET} {text}")


def mask(value: str) -> str:
    """A safe display value. Never returns the full secret."""
    text = str(value or "")
    if not text:
        return "(not set)"
    if len(text) <= 4:
        return f"**** ({len(text)} chars)"
    return f"{text[:2]}...{text[-2:]} ({len(text)} chars)"


def _secret_input(prompt: str) -> str:
    try:
        return getpass.getpass(f"  {prompt}: ")
    except (EOFError, KeyboardInterrupt):
        raise
    except Exception:
        return input(f"  {prompt}: ")


def ask(
    label: str,
    default: str = "",
    secret: bool = False,
    required: bool = False,
    validate=None,
) -> str:
    for _attempt in range(3):
        suffix = f" [{mask(default)}]" if (default and secret) else (f" [{default}]" if default else "")
        prompt = f"  {label}{suffix}: "
        try:
            value = _secret_input(label) if secret else input(prompt)
        except EOFError:
            value = ""
        except KeyboardInterrupt:
            raise InstallerCancelled()
        value = value.strip()
        if not value:
            value = default
        if required and not value:
            warn("This value is required.")
            continue
        if validate is not None:
            try:
                validate(value)
            except ValueError as exc:
                warn(str(exc))
                continue
        return value
    raise InstallerCancelled()


def confirm(label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"  {label} [{hint}]: ").strip().lower()
    except EOFError:
        return default
    except KeyboardInterrupt:
        raise InstallerCancelled()
    if not answer:
        return default
    return answer in {"y", "yes", "1", "true"}


def _int_validator(minimum: int = 1, maximum: int = 0):
    def _check(value: str) -> None:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError("Enter a whole number.") from None
        if number < minimum:
            raise ValueError(f"Must be at least {minimum}.")
        if maximum and number > maximum:
            raise ValueError(f"Must be at most {maximum}.")

    return _check


def _language_validator(value: str) -> None:
    if value.strip().lower() not in {"en", "fa", "persian", "farsi", "english"}:
        raise ValueError("Use en or fa.")


# ----------------------------------------------------------------------- checks
def check_system() -> List[Tuple[str, str, bool]]:
    results: List[Tuple[str, str, bool]] = []
    version = sys.version_info
    results.append(
        (
            "Python",
            f"{platform.python_version()} ({platform.system()})",
            version >= MIN_PYTHON,
        )
    )
    for package, label in (
        ("telethon", "Telethon"),
        ("pydantic", "Pydantic"),
        ("dotenv", "python-dotenv"),
        ("cryptography", "cryptography"),
    ):
        try:
            module = __import__(package)
            version_text = getattr(module, "__version__", "installed")
            results.append((label, str(version_text), True))
        except ImportError:
            results.append((label, "missing", False))
    try:
        import PIL  # noqa: F401

        results.append(("Pillow", "installed", True))
    except ImportError:
        results.append(("Pillow", "optional (media tools need it)", False))
    results.append(("SQLite", "available", True))
    return results


def validate_data_dir(path: str) -> str:
    if not path.strip():
        raise ValueError("A data directory is required.")
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".reze-write-test")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
    except OSError as exc:
        raise ValueError(f"The directory is not writable: {exc}") from exc
    return path


# -------------------------------------------------------------------------- env
def load_env(path: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not os.path.isfile(path):
        return values
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, _, raw = stripped.partition("=")
                values[key.strip()] = raw.strip().strip('"').strip("'")
    except OSError:
        return {}
    return values


def merge_env(existing_text: str, updates: Dict[str, str]) -> str:
    """Update keys in place, preserve comments and append new keys in order."""
    lines = existing_text.splitlines()
    seen = set()
    output: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                output.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        output.append(line)
    missing = [key for key in ENV_ORDER if key in updates and key not in seen]
    extra = sorted(key for key in updates if key not in seen and key not in ENV_ORDER)
    missing.extend(extra)
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# Added by the REZE installer")
        output.extend(f"{key}={updates[key]}" for key in missing)
    return "\n".join(output).rstrip() + "\n"


def write_env(path: str, updates: Dict[str, str]) -> Tuple[bool, str]:
    existing = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            existing = handle.read()
    content = merge_env(existing, updates)
    if content == existing:
        return False, "no changes"
    if existing:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = f"{path}.bak-{stamp}"
        shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True, "written"


# ------------------------------------------------------------------------ steps
def _telegram_step(values: Dict[str, str]) -> Dict[str, str]:
    updates = {}
    if not confirm("Configure the Telegram userbot now?", default=True):
        warn("Skipped. The web panel will run in panel-only mode until configured.")
        return updates
    updates["REZE_API_ID"] = ask(
        "Telegram API ID",
        default=values.get("REZE_API_ID", ""),
        required=True,
        validate=_int_validator(1),
    )
    updates["REZE_API_HASH"] = ask(
        "Telegram API hash (hidden)",
        default=values.get("REZE_API_HASH", ""),
        secret=True,
        required=True,
    )
    updates["REZE_SESSION_STRING"] = ask(
        "Session string (hidden, leave blank to log in on first start)",
        default=values.get("REZE_SESSION_STRING", ""),
        secret=True,
    )
    updates["REZE_OWNER_ID"] = ask(
        "Owner user ID (your numeric Telegram ID)",
        default=values.get("REZE_OWNER_ID", ""),
        required=True,
        validate=_int_validator(1),
    )
    updates["REZE_WEB_PORT"] = ask(
        "Web panel port",
        default=values.get("REZE_WEB_PORT", "8080"),
        validate=_int_validator(1, 65535),
    )
    if confirm("Set a panel password now?", default=bool(values.get("REZE_PANEL_PASSWORD"))):
        password = ask("Panel password (hidden)", secret=True, required=True)
        if len(password) < 8:
            warn("A short password is accepted but not recommended (minimum 8 characters advised).")
        updates["REZE_PANEL_PASSWORD"] = password
        updates["REZE_PANEL_USERNAME"] = ask(
            "Panel username", default=values.get("REZE_PANEL_USERNAME", "admin")
        )
    return updates


def _ai_step(values: Dict[str, str]) -> Dict[str, str]:
    updates = {}
    if not confirm("Configure an AI provider now? (optional)", default=False):
        return updates
    updates["REZE_AI_PROVIDER"] = ask(
        "Provider (openai, anthropic, gemini, openai_compatible)",
        default=values.get("REZE_AI_PROVIDER", "openai"),
    )
    updates["REZE_AI_MODEL"] = ask(
        "Model", default=values.get("REZE_AI_MODEL", "")
    )
    updates["REZE_AI_API_KEY"] = ask(
        "API key (hidden)", default=values.get("REZE_AI_API_KEY", ""), secret=True
    )
    updates["REZE_AI_BASE_URL"] = ask(
        "Base URL (optional)", default=values.get("REZE_AI_BASE_URL", "")
    )
    return updates


def _review(values: Dict[str, str]) -> None:
    say("")
    say(f"  {BOLD}Review{RESET} {DIM}(secrets masked){RESET}")
    for key in ENV_ORDER:
        value = values.get(key, "")
        shown = mask(value) if key in SECRET_KEYS else (value or "(not set)")
        say(f"  {key:<28} {shown}")


# ------------------------------------------------------------------------- menu
def settings_menu(env_path: str) -> None:
    """Post-install menu. Every optional feature is displayed OFF first."""
    say("")
    say(f"{CYAN}Post-install settings{RESET}")
    say(f"{DIM}Optional features are OFF by default. Nothing starts automatically.{RESET}")
    try:
        from reze.features import FEATURES, FeatureConfirmationRequired, features
    except Exception as exc:  # noqa: BLE001 - database may not be initialized
        warn(f"Feature menu unavailable: {exc}")
        return
    while True:
        say("")
        for index, spec in enumerate(FEATURES, start=1):
            state = "ON " if features.is_enabled(spec.key) else "OFF"
            sensitive = " *" if spec.sensitive else ""
            say(f"  {index:>2}. [{state}] {spec.key}{sensitive} — {spec.label}")
        say("")
        say(f"  {DIM}Commands: e <key> [confirm] · d <key> · l <en|fa> · s (state) · q (quit){RESET}")
        try:
            raw = input("  menu> ").strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            return
        if not raw:
            continue
        parts = raw.split()
        command = parts[0].lower()
        if command in {"q", "quit", "exit"}:
            return
        if command == "s":
            summary = features.summary()
            say(f"  Enabled: {summary['enabled']}/{summary['total']}")
            continue
        if command == "l" and len(parts) > 1:
            try:
                from reze.localization import set_language

                code = set_language(parts[1])
                values = load_env(env_path)
                values["REZE_LANGUAGE"] = code
                write_env(env_path, {"REZE_LANGUAGE": code})
                ok(f"Language set to {code}.")
            except Exception as exc:  # noqa: BLE001
                warn(str(exc))
            continue
        if command in {"e", "d"} and len(parts) > 1:
            key = parts[1].lower()
            try:
                if command == "d":
                    features.disable(key)
                    ok(f"{key} is OFF.")
                else:
                    features.enable(key, confirmed="confirm" in {value.lower() for value in parts[2:]})
                    ok(f"{key} is ON.")
            except FeatureConfirmationRequired:
                warn(f"Sensitive feature. Re-run with: e {key} confirm")
            except KeyError:
                warn(f"Unknown feature: {key}")
            continue
        warn("Unknown menu command. Try: e memory, d memory, l fa, q")


# ------------------------------------------------------------------------- main
def run(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="reze-install", description="REZE 3.0 installer")
    parser.add_argument("--env-file", default=".env", help="Path of the environment file to write")
    parser.add_argument("--data-dir", default="", help="Data directory (default: data)")
    parser.add_argument("--language", default="", choices=["", "en", "fa"])
    parser.add_argument("--check", action="store_true", help="Only run system checks")
    parser.add_argument("--non-interactive", action="store_true", help="Use defaults, no prompts")
    parser.add_argument("--yes", action="store_true", help="Accept all overwrite prompts")
    parser.add_argument("--no-menu", action="store_true", help="Skip the post-install menu")
    args = parser.parse_args(argv)

    say(f"{CYAN}{LOGO}{RESET}")
    say(f"  {DIM}REZE 3.0 installer · Ctrl+C cancels safely · secrets stay hidden{RESET}")

    checks = check_system()
    step(1, 8, "System check")
    fatal = False
    for label, detail, passed in checks:
        if passed:
            ok(f"{label}: {detail}")
        elif label == "Pillow":
            warn(f"{label}: {detail}")
        else:
            fail(f"{label}: {detail}")
            fatal = label != "Pillow"
    if fatal:
        say("")
        fail("Install the missing requirements, then run the installer again.")
        return 2
    if args.check:
        return 0

    env_path = args.env_file
    existing = load_env(env_path)
    values: Dict[str, str] = dict(existing)
    written = False
    interactive = not args.non_interactive

    try:
        if interactive:
            step(2, 8, "Telegram access")
            values.update(_telegram_step(existing))

            step(3, 8, "AI provider (optional)")
            values.update(_ai_step(existing))
        else:
            step(2, 8, "Telegram access")
            warn("Non-interactive mode: keeping existing Telegram settings.")
            step(3, 8, "AI provider (optional)")
            warn("Non-interactive mode: keeping existing AI settings.")

        step(4, 8, "Language")
        if args.language:
            language = args.language
        elif interactive:
            language = ask(
                "Language (en/fa)",
                default=existing.get("REZE_LANGUAGE", "en"),
                validate=_language_validator,
            )
        else:
            language = existing.get("REZE_LANGUAGE", "en")
        values["REZE_LANGUAGE"] = {"persian": "fa", "farsi": "fa", "english": "en"}.get(
            language.lower(), language.lower()
        )

        step(5, 8, "Storage and database")
        default_data = args.data_dir or existing.get("REZE_DATA_DIR", "data")
        data_dir = ask("Data directory", default=default_data) if interactive else default_data
        try:
            validate_data_dir(data_dir)
            ok(f"Writable: {os.path.abspath(data_dir)}")
        except ValueError as exc:
            fail(str(exc))
            return 1
        values["REZE_DATA_DIR"] = data_dir
        vault_enabled = interactive and confirm("Generate a Vault encryption key?", default=True)
        if not values.get("REZE_VAULT_KEY") and (vault_enabled or not interactive):
            values["REZE_VAULT_KEY"] = secrets.token_urlsafe(32)
            ok("Vault key generated (masked below; stored only in the env file).")

        step(6, 8, "Companion (optional)")
        if interactive and confirm("Configure the optional Telegram Bot Companion token now?", default=False):
            values["REZE_COMPANION_TOKEN"] = ask(
                "Bot token from @BotFather (hidden)", secret=True
            )

        if interactive:
            step(7, 8, "Review")
            _review(values)
            say("")
            if os.path.isfile(env_path) and not args.yes:
                if not confirm(f"{env_path} exists. Back it up and update it?", default=True):
                    raise InstallerCancelled()
        else:
            step(7, 8, "Review")
            warn("Non-interactive mode: writing the configuration without review.")

        updates = {key: value for key, value in values.items() if value != ""}
        changed, status = write_env(env_path, updates)
        written = changed
        if changed:
            ok(f"Configuration {status}: {env_path}")
        else:
            ok("Configuration already up to date; nothing was overwritten.")

        step(8, 8, "Database")
        initialise = args.yes or confirm("Initialize the database and apply migrations now?", default=True)
        if initialise:
            for key, value in updates.items():
                os.environ[key] = value
            try:
                from reze.database import db

                ok(f"Database ready at {db.db_path} (schema v{db.schema_version})")
            except Exception as exc:  # noqa: BLE001 - surfaced without secrets
                warn(f"Database initialization failed: {exc}")
                initialise = False
        else:
            warn("Skipped. The database is created on the first application start.")

        say("")
        say(f"{GREEN}{BOLD}REZE is configured.{RESET}")
        say(f"  Start it with: {BOLD}reze{RESET}")
        say("  Every optional feature is OFF until you enable it explicitly.")
        if initialise and not args.non_interactive and not args.no_menu and sys.stdin.isatty():
            settings_menu(env_path)
        return 0
    except InstallerCancelled:
        say("")
        warn("Cancelled. " + ("The configuration written so far was kept." if written else "Nothing was written."))
        return 130


def main(argv: Optional[List[str]] = None) -> None:
    try:
        code = run(argv)
    except KeyboardInterrupt:
        say("\n  Cancelled. Nothing else was changed.")
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
