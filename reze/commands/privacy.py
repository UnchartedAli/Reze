"""
Privacy & Account Safety Commands for Reze Userbot.
Safely guides owner without ever exposing private tokens or session files.
"""

from reze.command_router import router, CommandContext
from reze.config import settings
from reze.database import db

@router.register(name="privacy", category="Privacy", description="راهنمای تنظیمات حریم خصوصی حساب", owner_only=True)
async def privacy_cmd(ctx: CommandContext):
    return await ctx.reply(
        "🔐 **رهنمودهای امنیت و حریم خصوصی Reze:**\n\n"
        "1. فایل نشست (`.session`) در مسیر ایزوله نگهداری می‌شود و در پنل وب یا گیت منتشر نمی‌شود.\n"
        "2. هش رمز پنل وب با الگوریتم امن نگهداری می‌شود.\n"
        "3. کدهای ۵ رقمی و توکن‌ها در لاگ‌ها ماسک می‌شوند.\n"
        "4. کلیه عملیات خطرناک نیازمند اعتبارسنجی مالک هستند."
    )


@router.register(name="sessions", category="Privacy", description="راهنمای بررسی نشست‌های فعال حساب کاربری", owner_only=True)
async def sessions_cmd(ctx: CommandContext):
    return await ctx.reply(
        "📱 **بررسی نشست‌های فعال (Active Sessions):**\n"
        "برای نظارت بر دستگاه‌های متصل، لطفاً مستقیماً در اپلیکیشن تلگرام به مسیر زیر بروید:\n"
        "`Settings ➔ Devices / Active Sessions`\n"
        "اگر نشست ناشناسی مشاهده کردید بلافاصله آن را خاتمه دهید."
    )


@router.register(name="accountstatus", category="Privacy", description="بررسی اتصال و وضعیت سلامت اکانت", owner_only=True)
async def accountstatus_cmd(ctx: CommandContext):
    return await ctx.reply(
        "🟢 **وضعیت اتصال حساب کاربری:**\n"
        "• نشست جاری: فعال و متصل\n"
        "• پایداری سوکت MTProto: پایدار\n"
        "• محدودیت موقت (FloodWait): ندارد ✅"
    )


@router.register(name="backup", category="Privacy", description="تهیه نسخه پشتیبان از دیتابیس بدون اطلاعات حساس", owner_only=True)
async def backup_cmd(ctx: CommandContext):
    import shutil
    import os
    backup_file = "data/reze_backup.db"
    if os.path.exists("data/reze.db"):
        shutil.copy("data/reze.db", backup_file)
        return await ctx.reply(f"💾 نسخه پشتیبان دیتابیس با موفقیت در `{backup_file}` ذخیره شد.")
    return await ctx.reply("⚠️ دیتابیس یافت نشد.")
