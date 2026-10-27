"""
Moderation Commands for Reze Userbot.
Warnings, Rules, Greetings, Notes, Filters, Blacklists.
"""

from reze.command_router import router, CommandContext
from reze.database import db

@router.register(name="warn", category="Moderation", description="ثبت اخطار برای کاربر در گروه", admin_only=True, group_only=True)
async def warn_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply("⚠️ کاربر هدف را مشخص کنید.")
    reason = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else "بدون دلیل"
    count = db.add_warning(ctx.chat_id, target_id, ctx.sender_id, reason)
    
    reply_msg = f"⚠️ کاربر `{target_id}` اخطار دریافت کرد!\nتعداد اخطارها: `{count}/3`\nعلت: {reason}"
    if count >= 3:
        reply_msg += "\n🚨 کاربر به سقف اخطار رسید و باید محدود/اخراج شود."
    return await ctx.reply(reply_msg)


@router.register(name="unwarn", category="Moderation", description="کاهش یک اخطار از کاربر", admin_only=True, group_only=True)
async def unwarn_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply("⚠️ کاربر هدف را مشخص کنید.")
    count = db.remove_warning(ctx.chat_id, target_id)
    return await ctx.reply(f"✅ یک اخطار از کاربر `{target_id}` کسر شد. (اخطارهای باقی‌مانده: `{count}`)")


@router.register(name="warns", category="Moderation", description="مشاهده تعداد اخطارهای کاربر", group_only=True)
async def warns_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id() or ctx.sender_id
    count = db.get_warnings_count(ctx.chat_id, target_id)
    return await ctx.reply(f"ℹ️ کاربر `{target_id}` دارای `{count}` اخطار فعال است.")


@router.register(name="resetwarns", category="Moderation", description="پاک‌کردن تمام اخطارهای یک کاربر", admin_only=True, group_only=True)
async def resetwarns_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply("⚠️ کاربر هدف را مشخص کنید.")
    db.reset_warnings(ctx.chat_id, target_id)
    return await ctx.reply(f"🔄 تمام اخطارهای کاربر `{target_id}` پاک شدند.")


@router.register(name="rules", category="Moderation", description="مشاهده قوانین گروه", group_only=True)
async def rules_cmd(ctx: CommandContext):
    cfg = db.get_group_settings(ctx.chat_id)
    rules = cfg.get("rules") or "هنوز قانونی برای این گروه تنظیم نشده است."
    return await ctx.reply(f"📜 **قوانین گروه:**\n\n{rules}")


@router.register(name="setrules", category="Moderation", description="تنظیم قوانین گروه", admin_only=True, group_only=True)
async def setrules_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ متن قوانین را وارد کنید: `.setrules رعایت احترام الزامی است.`")
    rules_text = " ".join(ctx.args)
    db.update_group_settings(ctx.chat_id, rules=rules_text)
    return await ctx.reply("✅ قوانین گروه با موفقیت به‌روزرسانی شد.")


@router.register(name="welcome", category="Moderation", description="فعال یا غیرفعال‌سازی پیام خوشامدگویی", admin_only=True, group_only=True)
async def welcome_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply("⚠️ روش استفاده: `.welcome on` یا `.welcome off`")
    val = 1 if ctx.args[0].lower() == "on" else 0
    db.update_group_settings(ctx.chat_id, welcome_enabled=val)
    return await ctx.reply(f"✅ پیام خوشامدگویی {'فعال' if val else 'غیرفعال'} شد.")


@router.register(name="setwelcome", category="Moderation", description="تنظیم متن پیام خوشامدگویی", admin_only=True, group_only=True)
async def setwelcome_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ متن خوشامدگویی را وارد کنید. می‌توانید از {mention} و {title} استفاده کنید.")
    text = " ".join(ctx.args)
    db.update_group_settings(ctx.chat_id, welcome_text=text)
    return await ctx.reply("✅ متن خوشامدگویی گروه ثبت شد.")


@router.register(name="goodbye", category="Moderation", description="فعال یا غیرفعال‌سازی پیام خداحافظی", admin_only=True, group_only=True)
async def goodbye_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply("⚠️ روش استفاده: `.goodbye on` یا `.goodbye off`")
    val = 1 if ctx.args[0].lower() == "on" else 0
    db.update_group_settings(ctx.chat_id, goodbye_enabled=val)
    return await ctx.reply(f"✅ پیام خداحافظی {'فعال' if val else 'غیرفعال'} شد.")


@router.register(name="filter", category="Moderation", description="مدیریت پاسخ‌های خودکار (add, remove, list)", admin_only=True, group_only=True)
async def filter_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ روش استفاده:\n`.filter add <keyword> <reply>`\n`.filter remove <keyword>`\n`.filter list`")
    action = ctx.args[0].lower()
    if action == "add" and len(ctx.args) >= 3:
        kw = ctx.args[1]
        reply_txt = " ".join(ctx.args[2:])
        db.set_filter(ctx.chat_id, kw, reply_txt)
        return await ctx.reply(f"✅ فیلتر برای کلمه `{kw}` ذخیره شد.")
    elif action == "remove" and len(ctx.args) >= 2:
        kw = ctx.args[1]
        ok = db.remove_filter(ctx.chat_id, kw)
        return await ctx.reply("✅ فیلتر حذف شد." if ok else "⚠️ چنین فیلتری یافت نشد.")
    elif action == "list":
        flist = db.get_filters(ctx.chat_id)
        if not flist:
            return await ctx.reply("📋 هیچ فیلتری در این گروه ثبت نشده است.")
        return await ctx.reply("📋 **فیلترهای فعال:**\n" + "\n".join([f"• `{f['keyword']}` ➔ `{f['reply_text']}`" for f in flist]))
    return await ctx.reply("⚠️ دستور نامعتبر. راهنما: `.filter list`")


@router.register(name="blacklist", category="Moderation", description="مدیریت کلمات ممنوعه (add, remove, list)", admin_only=True, group_only=True)
async def blacklist_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ روش استفاده:\n`.blacklist add <word>`\n`.blacklist remove <word>`\n`.blacklist list`")
    action = ctx.args[0].lower()
    if action == "add" and len(ctx.args) >= 2:
        word = ctx.args[1]
        db.add_blacklist(ctx.chat_id, word)
        return await ctx.reply(f"🚫 کلمه `{word}` به لیست سیاه گروه اضافه شد.")
    elif action == "remove" and len(ctx.args) >= 2:
        word = ctx.args[1]
        ok = db.remove_blacklist(ctx.chat_id, word)
        return await ctx.reply("✅ کلمه از لیست سیاه حذف شد." if ok else "⚠️ کلمه در لیست سیاه نبود.")
    elif action == "list":
        blist = db.get_blacklists(ctx.chat_id)
        if not blist:
            return await ctx.reply("📋 لیست سیاه گروه خالی است.")
        return await ctx.reply("🚫 **کلمات ممنوعه:**\n" + ", ".join([f"`{b['trigger']}`" for b in blist]))
    return await ctx.reply("⚠️ دستور نامعتبر.")
