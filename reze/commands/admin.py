"""
Admin Commands for Reze Userbot.
Group management: .ban, .unban, .kick, .mute, .unmute, .purge, .del, .pin, .unpin, .admins, .tagall, .slowmode
"""

from reze.command_router import router, CommandContext
from reze.database import db
from reze.config import settings
from reze.logging_config import logger

@router.register(name="ban", category="Admin", description="مسدود کردن کاربر در گروه", admin_only=True, group_only=True)
async def ban_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply("⚠️ کاربر هدف را مشخص کنید (با ریپلای یا ارسال شناسه عددی).")
    
    # Check permissions & perform ban via MTProto
    try:
        if hasattr(ctx.client, "edit_permissions"):
            from telethon.tl.types import ChatBannedRights
            rights = ChatBannedRights(until_date=None, view_messages=True)
            await ctx.client.edit_permissions(ctx.chat_id, target_id, rights)
        db.log_admin_action("ban", ctx.sender_id, ctx.chat_id, target_id, "User banned")
        return await ctx.reply(f"🚫 کاربر `{target_id}` با موفقیت از گروه مسدود (Ban) شد.")
    except Exception as e:
        return await ctx.reply(f"❌ خطا در مسدودسازی کاربر: {e}")


@router.register(name="unban", category="Admin", description="رفع مسدودیت کاربر در گروه", admin_only=True, group_only=True)
async def unban_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply("⚠️ کاربر هدف را مشخص کنید.")
    
    try:
        if hasattr(ctx.client, "edit_permissions"):
            from telethon.tl.types import ChatBannedRights
            rights = ChatBannedRights(until_date=None, view_messages=False, send_messages=False)
            await ctx.client.edit_permissions(ctx.chat_id, target_id, rights)
        db.log_admin_action("unban", ctx.sender_id, ctx.chat_id, target_id, "User unbanned")
        return await ctx.reply(f"✅ مسدودیت کاربر `{target_id}` با موفقیت برداشته شد.")
    except Exception as e:
        return await ctx.reply(f"❌ خطا در رفع مسدودیت: {e}")


@router.register(name="kick", category="Admin", description="اخراج کاربر از گروه", admin_only=True, group_only=True)
async def kick_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply("⚠️ کاربر هدف را برای اخراج مشخص کنید.")
    try:
        if hasattr(ctx.client, "kick_participant"):
            await ctx.client.kick_participant(ctx.chat_id, target_id)
        db.log_admin_action("kick", ctx.sender_id, ctx.chat_id, target_id, "User kicked")
        return await ctx.reply(f"👢 کاربر `{target_id}` با موفقیت از گروه اخراج شد.")
    except Exception as e:
        return await ctx.reply(f"❌ خطا در اخراج کاربر: {e}")


@router.register(name="mute", category="Admin", description="محدود کردن ارسال پیام کاربر در گروه", admin_only=True, group_only=True)
async def mute_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply("⚠️ کاربر هدف را مشخص کنید.")
    try:
        if hasattr(ctx.client, "edit_permissions"):
            from telethon.tl.types import ChatBannedRights
            rights = ChatBannedRights(until_date=None, send_messages=True)
            await ctx.client.edit_permissions(ctx.chat_id, target_id, rights)
        db.log_admin_action("mute", ctx.sender_id, ctx.chat_id, target_id, "User muted")
        return await ctx.reply(f"🔇 کاربر `{target_id}` با موفقیت در گروه بی‌صدا (Mute) شد.")
    except Exception as e:
        return await ctx.reply(f"❌ خطا در بی‌صدا کردن کاربر: {e}")


@router.register(name="unmute", category="Admin", description="رفع محدودیت ارسال پیام کاربر", admin_only=True, group_only=True)
async def unmute_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply("⚠️ کاربر هدف را مشخص کنید.")
    try:
        if hasattr(ctx.client, "edit_permissions"):
            from telethon.tl.types import ChatBannedRights
            rights = ChatBannedRights(until_date=None, send_messages=False)
            await ctx.client.edit_permissions(ctx.chat_id, target_id, rights)
        db.log_admin_action("unmute", ctx.sender_id, ctx.chat_id, target_id, "User unmuted")
        return await ctx.reply(f"🔊 محدودیت ارسال پیام کاربر `{target_id}` برداشته شد.")
    except Exception as e:
        return await ctx.reply(f"❌ خطا در رفع محدودیت: {e}")


@router.register(name="purge", category="Admin", description="حذف پیام‌های اخیر در محدوده ایمن", admin_only=True, group_only=True)
async def purge_cmd(ctx: CommandContext):
    limit = 20
    if ctx.args and ctx.args[0].isdigit():
        limit = min(int(ctx.args[0]), settings.max_purge_limit)
    
    try:
        if hasattr(ctx.client, "iter_messages") and hasattr(ctx.client, "delete_messages"):
            msg_ids = []
            async for msg in ctx.client.iter_messages(ctx.chat_id, limit=limit):
                msg_ids.append(msg.id)
            if msg_ids:
                await ctx.client.delete_messages(ctx.chat_id, msg_ids)
        return await ctx.reply(f"🧹 تعداد `{limit}` پیام اخیر در گروه پاک‌سازی شد.")
    except Exception as e:
        return await ctx.reply(f"❌ خطا در پاک‌سازی پیام‌ها: {e}")


@router.register(name="del", category="Admin", description="حذف پیام ریپلای‌شده", admin_only=True)
async def del_cmd(ctx: CommandContext):
    if not ctx.is_reply:
        return await ctx.reply("⚠️ لطفاً روی پیامی که قصد حذف آن را دارید ریپلای کنید.")
    try:
        reply_msg = await ctx.message.get_reply_message() if hasattr(ctx.message, "get_reply_message") else None
        if reply_msg and hasattr(reply_msg, "delete"):
            await reply_msg.delete()
        if hasattr(ctx.message, "delete"):
            await ctx.message.delete()
        return None
    except Exception as e:
        return await ctx.reply(f"❌ خطا در حذف پیام: {e}")


@router.register(name="pin", category="Admin", description="سنجاق کردن پیام ریپلای‌شده", admin_only=True, group_only=True)
async def pin_cmd(ctx: CommandContext):
    if not ctx.is_reply:
        return await ctx.reply("⚠️ روی پیامی که می‌خواهید سنجاق شود ریپلای کنید.")
    try:
        reply_msg = await ctx.message.get_reply_message() if hasattr(ctx.message, "get_reply_message") else None
        if reply_msg and hasattr(ctx.client, "pin_message"):
            await ctx.client.pin_message(ctx.chat_id, reply_msg.id)
        return await ctx.reply("📌 پیام مورد نظر با موفقیت سنجاق شد.")
    except Exception as e:
        return await ctx.reply(f"❌ خطا در سنجاق پیام: {e}")


@router.register(name="unpin", category="Admin", description="برداشتن سنجاق پیام", admin_only=True, group_only=True)
async def unpin_cmd(ctx: CommandContext):
    try:
        if hasattr(ctx.client, "unpin_message"):
            await ctx.client.unpin_message(ctx.chat_id)
        return await ctx.reply("📌 سنجاق پیام با موفقیت برداشته شد.")
    except Exception as e:
        return await ctx.reply(f"❌ خطا: {e}")


@router.register(name="admins", category="Admin", description="نمایش لیست مدیران گروه", group_only=True)
async def admins_cmd(ctx: CommandContext):
    try:
        admin_list = []
        if hasattr(ctx.client, "get_participants"):
            from telethon.tl.types import ChannelParticipantsAdmins
            admins = await ctx.client.get_participants(ctx.chat_id, filter=ChannelParticipantsAdmins)
            for adm in admins:
                name = getattr(adm, "first_name", "Admin")
                admin_list.append(f"• [{name}](tg://user?id={adm.id}) (`{adm.id}`)")
        else:
            admin_list = [f"• مدیر فعلی: `{ctx.sender_id}`"]
        
        return await ctx.reply("👑 **لیست مدیران گروه:**\n\n" + "\n".join(admin_list))
    except Exception as e:
        return await ctx.reply(f"❌ خطا در دریافت لیست مدیران: {e}")


@router.register(name="tagall", category="Admin", description="منشن دسته‌بندی‌شده اعضای گروه با کنترل نرخ", admin_only=True, group_only=True)
async def tagall_cmd(ctx: CommandContext):
    msg_custom = " ".join(ctx.args) if ctx.args else "توجه همگانی"
    max_members = min(50, settings.max_tagall_limit)
    
    mentions = []
    try:
        if hasattr(ctx.client, "get_participants"):
            participants = await ctx.client.get_participants(ctx.chat_id, limit=max_members)
            for p in participants:
                if not getattr(p, "bot", False) and not getattr(p, "deleted", False):
                    name = getattr(p, "first_name", "User")
                    mentions.append(f"[{name}](tg://user?id={p.id})")
        else:
            mentions = [f"[@User_{i}](tg://user?id={i})" for i in range(1, 10)]
            
        chunks = [mentions[i:i + 5] for i in range(0, len(mentions), 5)]
        for chunk in chunks:
            text = f"📢 **{msg_custom}**\n\n" + " ".join(chunk)
            await ctx.client.send_message(ctx.chat_id, text)
        return None
    except Exception as e:
        return await ctx.reply(f"❌ خطا در اجرای Tagall: {e}")


@router.register(name="slowmode", category="Admin", description="تنظیم حالت آهسته در گروه (ثانیه)", admin_only=True, group_only=True)
async def slowmode_cmd(ctx: CommandContext):
    if not ctx.args or not ctx.args[0].isdigit():
        return await ctx.reply("⚠️ لطفاً ثانیه حالت کند را وارد کنید: `.slowmode 10` (0 برای غیرفعال‌سازی)")
    seconds = int(ctx.args[0])
    try:
        if hasattr(ctx.client, "set_slow_mode"):
            await ctx.client.set_slow_mode(ctx.chat_id, seconds)
        db.update_group_settings(ctx.chat_id, slowmode_seconds=seconds)
        return await ctx.reply(f"🐢 حالت آهسته گروه روی `{seconds}` ثانیه تنظیم شد.")
    except Exception as e:
        return await ctx.reply(f"❌ خطا در تنظیم حالت آهسته: {e}")
