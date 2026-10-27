"""
Security Commands for Reze Userbot.
AntiFlood, AntiRaid, AntiLink, Locks, CleanService.
"""

from reze.command_router import router, CommandContext
from reze.database import db

@router.register(name="antiflood", category="Security", description="فعال یا غیرفعال‌سازی سیستم ضد اسپم", admin_only=True, group_only=True)
async def antiflood_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply("⚠️ روش استفاده: `.antiflood on` یا `.antiflood off`")
    val = 1 if ctx.args[0].lower() == "on" else 0
    db.update_group_settings(ctx.chat_id, antiflood_enabled=val)
    return await ctx.reply(f"🛡️ سیستم ضداسپم (AntiFlood) {'فعال' if val else 'غیرفعال'} شد.")


@router.register(name="antiraid", category="Security", description="محافظت در برابر هجوم کاربران فیک", admin_only=True, group_only=True)
async def antiraid_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply("⚠️ روش استفاده: `.antiraid on` یا `.antiraid off`")
    val = 1 if ctx.args[0].lower() == "on" else 0
    db.update_group_settings(ctx.chat_id, antiraid_enabled=val)
    return await ctx.reply(f"🛡️ سیستم ضد هجوم (AntiRaid) {'فعال' if val else 'غیرفعال'} شد.")


@router.register(name="antilink", category="Security", description="حذف خودکار لینک‌های ارسال‌شده در گروه", admin_only=True, group_only=True)
async def antilink_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply("⚠️ روش استفاده: `.antilink on` یا `.antilink off`")
    val = 1 if ctx.args[0].lower() == "on" else 0
    db.update_group_settings(ctx.chat_id, antilink_enabled=val)
    return await ctx.reply(f"🔗 محافظت ارسال لینک (AntiLink) {'فعال' if val else 'غیرفعال'} شد.")


@router.register(name="cleanservice", category="Security", description="حذف خودکار پیام‌های پیوستن و خروج گروه", admin_only=True, group_only=True)
async def cleanservice_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply("⚠️ روش استفاده: `.cleanservice on` یا `.cleanservice off`")
    val = 1 if ctx.args[0].lower() == "on" else 0
    db.update_group_settings(ctx.chat_id, cleanservice_enabled=val)
    return await ctx.reply(f"🧹 پاک‌سازی خودکار پیام‌های سرویس تلگرام {'فعال' if val else 'غیرفعال'} شد.")


@router.register(name="lock", category="Security", description="قفل کردن ارسال رسانه، استیکر یا پیام در گروه", admin_only=True, group_only=True)
async def lock_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ نوع قفل را انتخاب کنید: `.lock stickers` / `.lock media` / `.lock links`")
    item = ctx.args[0].lower()
    return await ctx.reply(f"🔒 قفل `{item}` با موفقیت بر روی گروه اعمال شد.")


@router.register(name="unlock", category="Security", description="باز کردن قفل‌های گروه", admin_only=True, group_only=True)
async def unlock_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ نوع قفل را مشخص کنید: `.unlock stickers`")
    item = ctx.args[0].lower()
    return await ctx.reply(f"🔓 قفل `{item}` برداشته شد.")
