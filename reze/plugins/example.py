"""
Example Reze Plugin.
Demonstrates custom dot commands and integration with the command router.
"""

from reze.command_router import router, CommandContext

@router.register(
    name="hello",
    category="Custom Plugins",
    description="پلاگین نمونه: ارسال پیام سلام سفارشی",
    usage=".hello"
)
async def hello_plugin_cmd(ctx: CommandContext):
    user_name = getattr(ctx.message, "sender", None)
    return await ctx.reply(f"👋 درود از پلاگین اختصاصی Reze! همه سیستم‌ها به درستی کار می‌کنند.")


@router.register(
    name="calc",
    category="Custom Plugins",
    description="محاسبه‌گر ساده ریاضی",
    usage=".calc 2 + 2"
)
async def calc_plugin_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply("⚠️ لطفاً عبارت محاسباتی را وارد کنید: `.calc 15 * 4`")
    expr = " ".join(ctx.args)
    # Safe evaluation of basic math
    allowed = set("0123456789+-*/(). ")
    if not set(expr).issubset(allowed):
        return await ctx.reply("❌ فقط عملگرهای پایه ریاضی مجاز هستند.")
    try:
        result = eval(expr, {"__builtins__": None}, {})
        return await ctx.reply(f"🧮 **نتیجه:** `{result}`")
    except Exception as e:
        return await ctx.reply(f"❌ خطا در محاسبه: {e}")
