"""
Profile & Personalization Commands for Reze Userbot.
Clock, bio, templates, timezones, and profile safety limits.
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from reze.command_router import router, CommandContext
from reze.database import db

@router.register(name="setname", category="Profile", description="تنظیم نام نمایشی حساب کاربری", owner_only=True)
async def setname_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ لطفاً نام مورد نظر را وارد کنید: `.setname Ali`")
    name = " ".join(ctx.args)
    db.update_profile_settings(original_name=name)
    return await ctx.reply(f"✅ نام پایه اکانت روی `{name}` تنظیم شد.")


@router.register(name="setbio", category="Profile", description="تنظیم بیوگرافی حساب کاربری", owner_only=True)
async def setbio_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ لطفاً متن بیو را وارد کنید: `.setbio Hello World`")
    bio = " ".join(ctx.args)
    db.update_profile_settings(original_bio=bio)
    return await ctx.reply(f"✅ بیو پایه اکانت روی `{bio}` تنظیم شد.")


@router.register(name="nameclock", category="Profile", description="فعال یا غیرفعال‌سازی ساعت روی نام", owner_only=True)
async def nameclock_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply("⚠️ روش استفاده: `.nameclock on` یا `.nameclock off`")
    val = 1 if ctx.args[0].lower() == "on" else 0
    db.update_profile_settings(name_clock_enabled=val)
    status = "فعال" if val else "غیرفعال"
    return await ctx.reply(f"✅ نمایش ساعت روی نام {status} شد.")


@router.register(name="bioclock", category="Profile", description="فعال یا غیرفعال‌سازی ساعت روی بیو", owner_only=True)
async def bioclock_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply("⚠️ روش استفاده: `.bioclock on` یا `.bioclock off`")
    val = 1 if ctx.args[0].lower() == "on" else 0
    db.update_profile_settings(bio_clock_enabled=val)
    status = "فعال" if val else "غیرفعال"
    return await ctx.reply(f"✅ نمایش ساعت روی بیو {status} شد.")


@router.register(name="clockformat", category="Profile", description="تنظیم قالب زمانی ساعت", owner_only=True)
async def clockformat_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ فرمت زمانی را وارد کنید. نمونه: `.clockformat %H:%M`")
    fmt = ctx.args[0]
    db.update_profile_settings(clock_format=fmt)
    return await ctx.reply(f"✅ فرمت ساعت به `{fmt}` تغییر یافت.")


@router.register(name="timezone", category="Profile", description="تنظیم منطقه زمانی ساعت", owner_only=True)
async def timezone_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ منطقه زمانی را مشخص کنید. نمونه: `.timezone Asia/Tehran`")
    tz = ctx.args[0]
    try:
        ZoneInfo(tz)
    except Exception:
        return await ctx.reply(f"❌ منطقه زمانی `{tz}` نامعتبر است. نمونه‌های معتبر: `Asia/Tehran`, `UTC`, `Europe/London`")
    db.update_profile_settings(timezone=tz)
    return await ctx.reply(f"✅ منطقه زمانی به `{tz}` تغییر یافت.")


@router.register(name="clockstatus", category="Profile", description="نمایش وضعیت فعال بودن ساعت نام و بیو", owner_only=True)
async def clockstatus_cmd(ctx: CommandContext):
    cfg = db.get_profile_settings()
    return await ctx.reply(
        f"⏰ **وضعیت ساعت پروفایل:**\n"
        f"• ساعت نام: `{'فعال' if cfg.get('name_clock_enabled') else 'غیرفعال'}`\n"
        f"• ساعت بیو: `{'فعال' if cfg.get('bio_clock_enabled') else 'غیرفعال'}`\n"
        f"• منطقه زمانی: `{cfg.get('timezone', 'Asia/Tehran')}`\n"
        f"• قالب: `{cfg.get('clock_format', '%H:%M')}`\n"
        f"• آخرین به‌روزرسانی: `{cfg.get('last_updated', 'هیچ‌کدام')}`"
    )


@router.register(name="clockpreview", category="Profile", description="پیش‌نمایش متن نام و بیو با ساعت زنده", owner_only=True)
async def clockpreview_cmd(ctx: CommandContext):
    cfg = db.get_profile_settings()
    tz_str = cfg.get("timezone", "Asia/Tehran")
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("UTC")
    time_str = datetime.now(tz).strftime(cfg.get("clock_format", "%H:%M"))
    
    orig_name = cfg.get("original_name") or "Ali"
    name_tmpl = cfg.get("name_template") or "{name} | {time}"
    preview_name = name_tmpl.replace("{name}", orig_name).replace("{time}", time_str)
    
    orig_bio = cfg.get("original_bio") or "Reze Userbot"
    bio_tmpl = cfg.get("bio_template") or "{bio} • {time}"
    preview_bio = bio_tmpl.replace("{bio}", orig_bio).replace("{time}", time_str)
    
    return await ctx.reply(
        f"👁️ **پیش‌نمایش خروجی ساعت:**\n\n"
        f"📌 **نام:** `{preview_name}` (طول: {len(preview_name)}/64)\n"
        f"📌 **بیو:** `{preview_bio}` (طول: {len(preview_bio)}/70)"
    )


@router.register(name="setprefix", category="Profile", description="تغییر پیشوند دستورات با اعتبارسنجی", owner_only=True)
async def setprefix_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ پیشوند جدید را وارد کنید. نمونه: `.setprefix !`")
    new_prefix = ctx.args[0]
    if len(new_prefix) > 2:
        return await ctx.reply("❌ طول پیشوند نمی‌تواند بیش از 2 نویسه باشد.")
    router.prefix = new_prefix
    return await ctx.reply(f"✅ پیشوند دستورات با موفقیت به `{new_prefix}` تغییر یافت.")
