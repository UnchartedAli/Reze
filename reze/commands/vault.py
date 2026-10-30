"""
Digital Vault commands.

Secrets and small files are encrypted with AES-256-GCM before they touch the
database. The key is read from ``REZE_VAULT_KEY`` and is never printed, logged or
stored. Prefer replying to a message instead of typing a secret in the command
line, because the command message itself lives in Telegram's history.
"""

import os
import tempfile

from reze.command_router import CommandContext, router
from reze.features import require
from reze.storage.encryption import VaultDecryptError, VaultLocked
from reze.storage.vault.service import vault_service
from reze.ui import ascii

CATEGORY = "Security"


def _locked_message() -> str:
    return (
        "The Vault key is not configured. Set REZE_VAULT_KEY in the environment "
        "(a long random value) and restart REZE."
    )


@router.register(
    name="vault",
    category=CATEGORY,
    description="Store encrypted secrets and files, unlocked only by the owner.",
    usage=".vault [status|list|set <name> (reply with the secret)|put <name> (reply with a file)|get <name>|export <name>|delete <name>]",
    owner_only=True,
    cooldown=5,
    examples=[
        ".vault status",
        ".vault set openai (as a reply to the secret text)",
        ".vault get openai",
    ],
)
async def vault_cmd(ctx: CommandContext):
    hint = require("vault")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    action = (ctx.args[0].lower() if ctx.args else "status")

    if action == "status":
        status = vault_service.status()
        return await ctx.reply(
            ascii.section(
                "Digital Vault",
                [
                    f"Key: {'configured' if status['configured'] else 'NOT configured'}",
                    f"Key fingerprint: {status['fingerprint']}",
                    f"Entries: {status['entries']}",
                    f"Stored bytes: {status['bytes']}",
                    "" if status["configured"] else _locked_message(),
                ],
            )
        )

    if action == "list":
        rows = vault_service.list(limit=50)
        if not rows:
            return await ctx.reply(ascii.info("Vault is empty", ["Add an entry with .vault set <name>."]))
        lines = [
            f"#{row['id']} [{row['kind']}] {row['name']} — {row['size']} bytes · accessed {row['access_count']}x"
            for row in rows
        ]
        return await ctx.reply(ascii.section("Vault entries", lines))

    if not vault_service.configured:
        return await ctx.reply(ascii.warning("Vault locked", [_locked_message()]))

    if action == "set":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .vault set openai (reply to the secret)")
        name = ctx.args[1]
        reply = await ctx.get_reply_message()
        typed = " ".join(ctx.args[2:]).strip()
        value = typed or (getattr(reply, "message", "") if reply else "")
        if not value:
            return await ctx.reply_usage(
                "Reply to a message that contains the secret, or pass it after the name."
            )
        try:
            entry_id = vault_service.set_secret(name, value)
        except (VaultLocked, ValueError) as exc:
            return await ctx.reply(ascii.warning("Vault error", [str(exc)]))
        return await ctx.reply(
            ascii.success(
                "Secret encrypted",
                [f"Name: {name}", f"ID: {entry_id}", f"Bytes: {len(value)}"],
                footer="Delete the source message if it contained a secret",
            )
        )

    if action == "put":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Reply to a file with: .vault put <name>")
        name = ctx.args[1]
        reply = await ctx.get_reply_message()
        if reply is None or not getattr(reply, "media", None):
            return await ctx.reply_usage("Reply to a file with: .vault put <name>")
        directory = tempfile.mkdtemp(prefix="reze-vault-")
        path = os.path.join(directory, "upload.bin")
        try:
            downloaded = await reply.download_media(file=path)
            if not downloaded or not os.path.isfile(path):
                return await ctx.reply(ascii.warning("Download failed", ["The file was not received."]))
            entry_id = vault_service.put_file(name, path)
        except (VaultLocked, ValueError) as exc:
            return await ctx.reply(ascii.warning("Vault error", [str(exc)]))
        finally:
            try:
                os.remove(path)
                os.rmdir(directory)
            except OSError:
                pass
        return await ctx.reply(
            ascii.success("File encrypted", [f"Name: {name}", f"ID: {entry_id}"])
        )

    if action == "get":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .vault get openai")
        name = ctx.args[1]
        try:
            value = vault_service.get_secret(name)
        except KeyError:
            return await ctx.reply(ascii.warning("Not found", ["No Vault entry with that name."]))
        except (VaultLocked, VaultDecryptError) as exc:
            return await ctx.reply(ascii.warning("Vault error", [str(exc)]))
        return await ctx.reply(
            ascii.section(f"Vault: {name}", [value], footer="Owner-only · delete this message when done")
        )

    if action == "export":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .vault export notes")
        name = ctx.args[1]
        meta = vault_service.get_meta(name)
        if meta is None:
            return await ctx.reply(ascii.warning("Not found", ["No Vault entry with that name."]))
        directory = tempfile.mkdtemp(prefix="reze-vault-export-")
        path = os.path.join(directory, meta.get("filename") or "export.bin")
        try:
            vault_service.export(name, path)
            await ctx.send_file(path, caption=f"Vault export: {meta['name']}")
        except (VaultLocked, VaultDecryptError) as exc:
            return await ctx.reply(ascii.warning("Vault error", [str(exc)]))
        finally:
            try:
                os.remove(path)
                os.rmdir(directory)
            except OSError:
                pass
        return None

    if action == "delete":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .vault delete openai")
        name = ctx.args[1]
        if not vault_service.delete(name):
            return await ctx.reply(ascii.warning("Not found", ["No Vault entry with that name."]))
        return await ctx.reply(ascii.success("Vault entry deleted", [f"Name: {name}"]))

    return await ctx.reply_usage("Subcommands: status, list, set, put, get, export, delete.")
