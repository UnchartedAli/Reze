#!/usr/bin/env python3
"""
Generate a portable Telethon StringSession for Reze.

This is the recommended way to run Reze on Render, Railway, Koyeb, Fly.io or
any other platform with an ephemeral filesystem / no interactive terminal.

Usage (run this on your own computer, NOT inside the hosting service):

    # Fresh login (asks for api_id, api_hash, phone, code and 2FA password)
    python scripts/generate_session.py

    # Convert an existing Telethon .session file to a string
    python scripts/generate_session.py --from-file data/reze.session \
        --api-id 123456 --api-hash abcdef...

    # Write the string to a custom path
    python scripts/generate_session.py --output data/session_string.txt

Then put the printed value in the platform dashboard as REZE_SESSION_STRING.
Never commit or share the session string: it grants full access to the account.

Developer: UnchartedAli · Channel: @yamods
"""

import argparse
import asyncio
import getpass
import os
import sys

# Pick up REZE_API_ID / REZE_API_HASH from a local .env when present.
try:
    from dotenv import load_dotenv

    try:
        load_dotenv(interpolate=False)
    except TypeError:  # older python-dotenv
        load_dotenv()
except ImportError:
    pass

try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    from telethon.sessions import StringSession
except ImportError:
    print("Error: telethon is not installed.")
    print("Install the project requirements first:  pip install -r requirements.txt")
    sys.exit(1)


def _prompt_api_credentials(args):
    api_id = args.api_id or os.getenv("REZE_API_ID")
    api_hash = args.api_hash or os.getenv("REZE_API_HASH")

    if not api_id:
        api_id = input("Telegram API ID (my.telegram.org): ").strip()
    if not api_hash:
        api_hash = input("Telegram API HASH: ").strip()

    try:
        api_id_int = int(str(api_id).strip())
    except (TypeError, ValueError):
        print("Error: API ID must be a number.")
        sys.exit(1)

    api_hash = str(api_hash).strip()
    if not api_hash:
        print("Error: API HASH is required.")
        sys.exit(1)

    return api_id_int, api_hash


async def _login_interactively(api_id: int, api_hash: str, phone: str) -> str:
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            if not phone:
                phone = os.getenv("REZE_PHONE") or input(
                    "Phone number in international format (+98912...): "
                ).strip()
            await client.send_code_request(phone)
            code = input("Telegram verification code: ").strip()
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                password = getpass.getpass("Two-step verification password: ")
                await client.sign_in(password=password)

        if not await client.is_user_authorized():
            raise RuntimeError("Login was not completed. Please run the script again.")

        me = await client.get_me()
        if me:
            print(f"Logged in successfully (id: {me.id}).")

        return StringSession.save(client.session)
    finally:
        await client.disconnect()


async def _convert_file(session_file: str, api_id: int, api_hash: str) -> str:
    if not os.path.exists(session_file):
        print(f"Error: session file not found: {session_file}")
        sys.exit(1)

    client = TelegramClient(session_file, api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print("Error: this session file is not authorized.")
            sys.exit(1)
        return StringSession.save(client.session)
    finally:
        await client.disconnect()


def _save_session_string(session_string: str, output: str) -> None:
    parent = os.path.dirname(os.path.abspath(output))
    os.makedirs(parent, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(session_string)
    try:
        os.chmod(output, 0o600)
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Telethon StringSession for Reze")
    parser.add_argument("--from-file", help="Existing Telethon .session file to convert")
    parser.add_argument("--api-id", help="Telegram API ID (default: REZE_API_ID)")
    parser.add_argument("--api-hash", help="Telegram API HASH (default: REZE_API_HASH)")
    parser.add_argument("--phone", help="Phone number in international format")
    parser.add_argument(
        "--output",
        default="data/session_string.txt",
        help="Where to save the string (default: data/session_string.txt)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Only print the string, do not write it to disk",
    )
    args = parser.parse_args()

    api_id, api_hash = _prompt_api_credentials(args)

    if args.from_file:
        session_string = asyncio.run(_convert_file(args.from_file, api_id, api_hash))
    else:
        session_string = asyncio.run(_login_interactively(api_id, api_hash, args.phone))

    print()
    print("=" * 72)
    print("Copy the value after '=' into REZE_SESSION_STRING:")
    print(f"REZE_SESSION_STRING={session_string}")
    print("=" * 72)

    if not args.no_save:
        _save_session_string(session_string, args.output)
        print(f"\nSaved to: {os.path.abspath(args.output)} (permissions 0600)")
        print("You can also read this file from a persistent volume later.")

    print(
        "\nNext step: add the value above as REZE_SESSION_STRING in your hosting "
        "platform's environment variables (Render / Railway / Koyeb / Fly / VPS .env)."
    )
    print("Security: never commit, paste in chat, or share this string - it grants")
    print("full access to your Telegram account. Revoke it from Telegram Settings >")
    print("Devices if it ever leaks.")


if __name__ == "__main__":
    # Telethon behaves best with the selector loop on Windows.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
