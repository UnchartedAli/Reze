"""
Example Reze plugin.

It demonstrates the full contract a plugin must honour:

* export a ``MANIFEST`` dictionary (validated on load);
* declare every ``@router.register`` call in ``MANIFEST["commands"]``;
* request only the capabilities it actually uses;
* use the shared ASCII renderer for output;
* define configuration through ``MANIFEST["config"]`` and read it through
  :class:`reze.plugin_manager.PluginSettings`.
"""

import ast
import operator

from reze.command_router import CommandContext, router
from reze.plugin_manager import PluginSettings
from reze.ui import ascii

MANIFEST = {
    "name": "Example Plugin",
    "id": "example",
    "version": "2.0.0",
    "description": "Reference plugin: themed greeting and a safe arithmetic calculator.",
    "author": "UnchartedAli",
    "source": "built-in",
    "category": "Plugins",
    "tags": ["example", "reference"],
    "commands": ["hello", "calc"],
    "permissions": ["telegram.message"],
    "min_reze_version": "2.0.0",
    "config": {
        "greeting": {
            "type": "string",
            "default": "All systems operational.",
            "description": "Text appended by .hello",
        }
    },
}

_settings = PluginSettings("example", MANIFEST["config"])

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval(expression: str) -> float:
    """Evaluate a numeric expression without ``eval`` of arbitrary code."""
    if len(expression) > 120:
        raise ValueError("Expression is too long.")
    tree = ast.parse(expression, mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](_eval(node.operand))
        raise ValueError("Only numbers and + - * / // % ** are allowed.")

    result = _eval(tree)
    if isinstance(result, complex):
        raise ValueError("Complex results are not supported.")
    return result


@router.register(
    name="hello",
    category="Plugins",
    description="Example plugin: send a themed greeting and its configuration value.",
    usage=".hello",
    permissions=("telegram.message",),
    examples=[".hello"],
)
async def hello_cmd(ctx: CommandContext):
    greeting = _settings.get("greeting")
    return await ctx.reply(
        ascii.panel(
            "ok",
            "Hello from a plugin",
            [
                f"Greeting: {greeting}",
                "Manifest, permissions and settings are validated by the plugin manager.",
            ],
            footer="Plugin: example v2.0.0",
        )
    )


@router.register(
    name="calc",
    category="Plugins",
    description="Safely evaluate a basic arithmetic expression.",
    usage=".calc <expression>",
    cooldown=1,
    examples=[".calc 12 * (3 + 4)"],
)
async def calc_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .calc 15 * 4")
    expression = ctx.args_text
    try:
        result = safe_eval(expression)
    except ValueError as exc:
        return await ctx.reply(ascii.error("Calculation failed", [str(exc)]))
    except SyntaxError:
        return await ctx.reply(ascii.error("Calculation failed", ["The expression is not valid."]))
    return await ctx.reply(
        ascii.success("Result", [f"{ascii.code(expression)} = {ascii.code(result)}"])
    )
