"""
Plugin Management Commands.
.plugins, .plugin enable/disable/info
"""

from reze.command_router import router, CommandContext
from reze.plugin_manager import plugin_manager

@router.register(name="plugins", category="Plugins", description="مشاهده لیست پلاگین‌های نصب‌شده", owner_only=True)
async def plugins_cmd(ctx: CommandContext):
    loaded = plugin_manager.loaded_plugins
    if not loaded:
        return await ctx.reply("🧩 در حال حاضر هیچ پلاگینی فعال نیست.")
    
    lines = ["🧩 **لیست پلاگین‌های فعال Reze:**\n"]
    for p_name in sorted(loaded.keys()):
        cmds = plugin_manager.plugin_commands.get(p_name, [])
        cmds_str = ", ".join([f"`.{c}`" for c in cmds]) if cmds else "بدون دستور"
        lines.append(f"• **{p_name}** ➔ دستورات: {cmds_str}")
    return await ctx.reply("\n".join(lines))


@router.register(name="plugin", category="Plugins", description="مدیریت وضعیت پلاگین‌ها (enable, disable, info)", owner_only=True)
async def plugin_manage_cmd(ctx: CommandContext):
    if len(ctx.args) < 2:
        return await ctx.reply("⚠️ روش استفاده:\n`.plugin info <name>`\n`.plugin disable <name>`\n`.plugin enable <name>`")
    
    action = ctx.args[0].lower()
    name = ctx.args[1].lower()
    
    if action == "info":
        if name in plugin_manager.loaded_plugins:
            cmds = plugin_manager.plugin_commands.get(name, [])
            return await ctx.reply(f"ℹ️ **اطلاعات پلاگین {name}:**\nوضعیت: فعال ✅\nدستورات ثبت‌شده: {cmds}")
        return await ctx.reply(f"⚠️ پلاگین `{name}` یافت نشد یا غیرفعال است.")
    
    elif action == "disable":
        if name in plugin_manager.loaded_plugins:
            plugin_manager.unload_plugin(name)
            return await ctx.reply(f"🛑 پلاگین `{name}` با موفقیت غیرفعال شد.")
        return await ctx.reply(f"⚠️ پلاگین `{name}` فعال نبود.")
        
    elif action == "enable":
        try:
            plugin_manager.load_plugin(name)
            return await ctx.reply(f"✅ پلاگین `{name}` با موفقیت بارگذاری و فعال شد.")
        except Exception as e:
            return await ctx.reply(f"❌ خطا در فعال‌سازی پلاگین: {e}")
            
    return await ctx.reply("⚠️ دستور نامعتبر.")
