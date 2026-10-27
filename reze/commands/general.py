"""
General Commands for Reze Userbot.
.help, .ping, .alive, .credits, .info, .id, .stats, .uptime, .version, .settings, .logs, .webpanel, .shutdown, .restart
"""

import time
import sys
import os
from datetime import datetime, timedelta
from reze.command_router import router, CommandContext
from reze import __author__, __channel__, __channel_url__, __version__
from reze.config import settings
from reze.database import db
from reze.logging_config import LOG_BUFFER

START_TIME = time.time()

@router.register(
    name="help",
    category="General",
    description="نمایش راهنمای جامع دستورات یا راهنمای یک بخش خاص",
    usage=".help [category]"
)
async def help_cmd(ctx: CommandContext):
    target = ctx.args[0].lower() if ctx.args else None
    
    if target:
        matching = [c for c in router.commands.values() if c.category.lower() == target]
        if not matching:
            return await ctx.reply(f"⚠️ دسته‌بندی `{target}` یافت نشد.\nدسته‌بندی‌های موجود: General, Profile, Admin, Moderation, Security, Privacy, Plugins")
        
        lines = [f"📖 **راهنمای دستورات بخش {target.title()}:**\n"]
        for cmd in sorted(matching, key=lambda x: x.name):
            lines.append(f"• `.{cmd.name}` — {cmd.description}")
        return await ctx.reply("\n".join(lines))
    
    categories = {}
    for cmd in router.commands.values():
        categories.setdefault(cmd.category, []).append(cmd.name)
    
    lines = [
        f"🌸 **راهنمای Reze Userbot** — ساخته‌شده توسط {__author__}\n",
        f"نسخه: `{__version__}` | پیشوند: `{router.prefix}` | کانال: {__channel__}\n"
    ]
    for cat, cmds in sorted(categories.items()):
        lines.append(f"🔹 **{cat}** ({len(cmds)} دستور):")
        lines.append(", ".join([f"`{c}`" for c in sorted(cmds)]))
        lines.append("")
    lines.append("💡 برای جزئیات هر بخش: `.help <category>`")
    return await ctx.reply("\n".join(lines))


@router.register(name="ping", category="General", description="بررسی زمان پاسخ‌دهی و تاخیر سرویس")
async def ping_cmd(ctx: CommandContext):
    start = time.time()
    latency = round((time.time() - start) * 1000, 2)
    return await ctx.reply(f"🏓 **Pong!**\n⏱️ تاخیر پردازش: `{latency}ms`")


@router.register(name="alive", category="General", description="بررسی زنده بودن و وضعیت کلی یوزربات")
async def alive_cmd(ctx: CommandContext):
    uptime_sec = int(time.time() - START_TIME)
    uptime_str = str(timedelta(seconds=uptime_sec))
    return await ctx.reply(
        f"✨ **Reze Userbot Is Alive & Operational!**\n"
        f"• نسخه: `v{__version__}`\n"
        f"• مدت فعالیت: `{uptime_str}`\n"
        f"• وضعیت سیستم: پایدار و ایمن ✅\n"
        f"• سازنده: **{__author__}** | کانال: {__channel__}"
    )


@router.register(
    name="credits",
    category="General",
    description="نمایش سازنده و کانال رسمی پروژه Reze",
    aliases=["creator", "developer", "support"],
)
async def credits_cmd(ctx: CommandContext):
    return await ctx.reply(
        f"🌸 **Reze Telegram Userbot**\n\n"
        f"👤 سازنده و توسعه‌دهنده: **{__author__}**\n"
        f"📣 کانال رسمی: **{__channel}**\n"
        f"🔗 لینک کانال: {__channel_url__}\n"
        f"🏷️ نسخه: `{__version__}`\n\n"
        f"💚 با عضویت در کانال از توسعه پروژه حمایت کنید."
    )


@router.register(name="info", category="General", description="اطلاعات کلی اکانت و وضعیت اتصال")
async def info_cmd(ctx: CommandContext):
    return await ctx.reply(
        f"👤 **Reze Account Info**\n"
        f"• مالک شناسه: `{settings.owner_id}`\n"
        f"• منطقه زمانی: `{settings.timezone}`\n"
        f"• دیتابیس: `SQLite (WAL mode)`\n"
        f"• بک‌اند سشن: `{settings.session_backend}`\n"
        f"• پلتفرم استقرار: `{settings.platform_name}`"
    )


@router.register(name="id", category="General", description="دریافت شناسه کاربر، گروه یا پیام")
async def id_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id() or ctx.sender_id
    lines = [
        f"🆔 **شناسه‌ها:**",
        f"• کاربر: `{target_id}`",
        f"• چت/گروه: `{ctx.chat_id}`"
    ]
    if ctx.is_reply:
        lines.append(f"• پیام ریپلای: `{getattr(ctx.message, 'reply_to_msg_id', 'N/A')}`")
    return await ctx.reply("\n".join(lines))


@router.register(name="stats", category="General", description="آمار داخلی اجرای دستورات و خطاهای ثبت‌شده")
async def stats_cmd(ctx: CommandContext):
    stats = db.get_stats()
    return await ctx.reply(
        f"📊 **آمار Reze Userbot:**\n"
        f"• دستورات اجراشده: `{router.total_executed}`\n"
        f"• خطاهای رخ‌داده: `{router.errors_count}`\n"
        f"• گروه‌های پیکربندی‌شده: `{stats.get('groups', 0)}`\n"
        f"• فیلترهای ثبت‌شده: `{stats.get('filters', 0)}`\n"
        f"• یادداشت‌ها: `{stats.get('notes', 0)}`\n"
        f"• اخطارها: `{stats.get('warnings', 0)}`"
    )


@router.register(name="uptime", category="General", description="مدت زمان اجرای پروسه")
async def uptime_cmd(ctx: CommandContext):
    uptime_sec = int(time.time() - START_TIME)
    return await ctx.reply(f"⏳ **Uptime:** `{str(timedelta(seconds=uptime_sec))}`")


@router.register(name="version", category="General", description="نمایش نگارش جاری Reze")
async def version_cmd(ctx: CommandContext):
    return await ctx.reply(
        f"🚀 **Reze Userbot** version `{__version__}` (Production Ready)\n"
        f"👤 سازنده: **{__author__}** | 📣 کانال: {__channel__}"
    )


@router.register(name="settings", category="General", description="نمایش تنظیمات فعال ربات", owner_only=True)
async def settings_cmd(ctx: CommandContext):
    return await ctx.reply(
        f"⚙️ **تنظیمات فعال Reze:**\n"
        f"• پیشوند: `{router.prefix}`\n"
        f"• منطقه زمانی: `{settings.timezone}`\n"
        f"• فاصله ساعت: `{settings.clock_interval_minutes} دقیقه`\n"
        f"• وب پنل پورت: `{settings.web_port}`\n"
        f"• سطح لاگ: `{settings.log_level}`"
    )


@router.register(name="webpanel", category="General", description="دریافت آدرس پنل وب مدیریت", owner_only=True)
async def webpanel_cmd(ctx: CommandContext):
    url = settings.display_url
    return await ctx.reply(
        f"🌐 **پنل وب Reze:**\n"
        f"آدرس ورود: {url}\n"
        f"نام کاربری: `{settings.panel_username}`\n"
        f"سلامت سرویس: `{url.rstrip('/')}{settings.healthcheck_path}`\n"
        f"⚠️ برای تغییر رمز از اسکریپت `scripts/generate_hash.py` استفاده کنید."
    )


@router.register(name="logs", category="General", description="مشاهده آخرین خطوط لاگ سیستم", owner_only=True)
async def logs_cmd(ctx: CommandContext):
    if not LOG_BUFFER:
        return await ctx.reply("📋 در حال حاضر هیچ لاگی در بافر ثبت نشده است.")
    recent = list(LOG_BUFFER)[-10:]
    lines = ["📋 **آخرین لاگ‌های Reze:**\n"]
    for item in recent:
        lines.append(f"`[{item.get('level')}]` {item.get('message')}")
    return await ctx.reply("\n".join(lines))


@router.register(name="shutdown", category="General", description="توقف امن سرویس یوزربات", owner_only=True)
async def shutdown_cmd(ctx: CommandContext):
    await ctx.reply("🛑 در حال خاموش کردن امن سرویس Reze...")
    sys.exit(0)


@router.register(name="restart", category="General", description="راه‌اندازی مجدد پروسه یوزربات", owner_only=True)
async def restart_cmd(ctx: CommandContext):
    await ctx.reply("🔄 در حال راه‌اندازی مجدد سرویس...")
    os.execv(sys.executable, [sys.executable] + sys.argv)
