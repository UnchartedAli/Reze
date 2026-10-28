"""
Extreme-ASCII message engine.

Every user-facing response in Reze is built here instead of being duplicated in
each command module. The renderer guarantees four properties:

* **ASCII identity** — banners, framed sections, tagged status lines and
  separators that render consistently in Telegram's monospace-free text.
* **Markdown safety** — decoration never uses Telegram Markdown control
  characters, and user-controlled values are escaped with :func:`escape_md`.
* **Length safety** — :func:`split_text` keeps every message under Telegram's
  4096 character limit without cutting words or URLs when it can be avoided.
* **Mobile readability** — frames default to 40 columns, the ``COMPACT`` theme
  drops them entirely, and long values wrap instead of overflowing.
"""

import re
import textwrap
from typing import Iterable, List, Optional, Sequence, Tuple

from reze import __version__
from reze.ui.themes import DEFAULT_THEME, THEMES, Theme, get_theme, theme_names

MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MD_SPECIALS = "\\_*`["


# --------------------------------------------------------------------- helpers
def active_theme_name() -> str:
    """Theme selected in the user preferences (falls back to the default)."""
    try:
        from reze.preferences import get_pref

        return get_pref("theme", DEFAULT_THEME) or DEFAULT_THEME
    except Exception:  # pragma: no cover - preferences unavailable (early boot)
        return DEFAULT_THEME


def theme_for(name: Optional[str] = None) -> Theme:
    return get_theme(name or active_theme_name())


def escape_md(value: object) -> str:
    """Escape Telegram MarkdownV1 control characters in untrusted text."""
    text = "" if value is None else str(value)
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    for char in _MD_SPECIALS:
        text = text.replace(char, "\\" + char)
    return text


def code(value: object) -> str:
    """Render a value as an inline code span, safely."""
    text = "" if value is None else str(value)
    text = _ANSI_RE.sub("", text).replace("`", "'")
    text = _CONTROL_RE.sub("", text)
    return f"`{text}`"


def sanitize(value: object) -> str:
    """Remove ANSI escapes and control characters from arbitrary text."""
    text = "" if value is None else str(value)
    return _CONTROL_RE.sub("", _ANSI_RE.sub("", text))


def split_text(text: str, limit: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """
    Split *text* into Telegram-safe chunks.

    Splitting prefers newline boundaries, never breaks inside a word unless a
    single line is longer than the limit, and preserves the original order.
    """
    if limit < 64:
        raise ValueError("The split limit must be at least 64 characters.")
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return [text]

    # Leave a small headroom so re-balancing code spans cannot overflow.
    limit = limit - 4

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0

    for raw_line in text.split("\n"):
        line = raw_line
        # A single line longer than the limit is hard-split on word boundaries.
        while len(line) > limit:
            window = line[:limit]
            cut = window.rfind(" ")
            if cut < limit // 2:
                cut = limit
            piece, line = line[:cut], line[cut:].lstrip(" ")
            if current:
                flush()
            chunks.append(piece)
        addition = len(line) + (1 if current else 0)
        if current_len + addition > limit:
            flush()
        current.append(line)
        current_len += addition
    flush()
    # A split inside an inline code span would break Telegram's Markdown
    # parser, so unbalanced chunks are closed and reopened on the next one.
    balanced: List[str] = []
    carry = False
    for chunk in chunks:
        if chunk == "":
            continue
        piece = ("`" if carry else "") + chunk
        if piece.count("`") % 2 == 1:
            piece += "`"
            carry = True
        else:
            carry = False
        balanced.append(piece)
    return balanced


def _wrap(text: str, width: int) -> List[str]:
    """Wrap a value to the frame width without breaking words or URLs."""
    text = sanitize(text)
    if width < 8:
        width = 8
    out: List[str] = []
    for line in text.split("\n"):
        if not line:
            out.append("")
            continue
        if len(line) <= width:
            out.append(line)
            continue
        out.extend(
            textwrap.wrap(
                line,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
            )
        )
    return out


def _as_lines(lines) -> List[str]:
    if lines is None:
        return []
    if isinstance(lines, str):
        return lines.split("\n")
    return [str(item) for item in lines]


# ---------------------------------------------------------------------- blocks
_BLOCK_BANNER = (
    "██████╗ ███████╗███████╗███████╗",
    "██╔══██╗██╔════╝╚══███╔╝██╔════╝",
    "██████╔╝█████╗    ███╔╝ █████╗  ",
    "██╔══██╗██╔══╝   ███╔╝  ██╔══╝  ",
    "██║  ██║███████╗███████╗███████╗",
    "╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝",
)


def banner(theme: Optional[str] = None) -> str:
    """The REZE 2.0 identity block."""
    selected = theme_for(theme)
    if selected.banner_style == "line":
        return f"REZE 2.0 // PERSONAL TELEGRAM OS // v{__version__}"
    body = "\n".join("  " + row for row in _BLOCK_BANNER)
    return f"{body}\n\n  PERSONAL TELEGRAM OS  //  v{__version__}"


def divider(theme: Optional[str] = None, width: Optional[int] = None) -> str:
    selected = theme_for(theme)
    if selected.compact:
        return "  " + "─" * 20
    span = max(12, (width or selected.width) - 2)
    return selected.lt + selected.h * span + selected.rt


def frame(
    title: str,
    lines=None,
    footer: Optional[str] = None,
    theme: Optional[str] = None,
    width: Optional[int] = None,
) -> str:
    """Render a titled frame around *lines*."""
    selected = theme_for(theme)
    body = _as_lines(lines)
    heading = sanitize(title).upper()

    if selected.compact:
        out = [f"{selected.accent} {heading}"]
        for line in body:
            for wrapped in _wrap(line, selected.width - 2):
                out.append(("  " + wrapped).rstrip())
        if footer:
            out.append(("  " + sanitize(footer)).rstrip())
        return "\n".join(out)

    total = max(24, width or selected.width)
    inner = total - 4  # two padding spaces plus both borders

    out = [selected.tl + selected.h * (total - 2) + selected.tr]
    out.append(f"{selected.v} {selected.accent} {heading}".ljust(total - 1) + selected.v)
    if body:
        out.append(selected.lt + selected.h * (total - 2) + selected.rt)
    for line in body:
        for wrapped in _wrap(line, inner):
            out.append(f"{selected.v} {wrapped}".ljust(total - 1) + selected.v)
    if footer:
        out.append(selected.lt + selected.h * (total - 2) + selected.rt)
        for wrapped in _wrap(footer, inner):
            out.append(f"{selected.v} {wrapped}".ljust(total - 1) + selected.v)
    out.append(selected.bl + selected.h * (total - 2) + selected.br)
    return "\n".join(out)


def section(title: str, lines=None, theme: Optional[str] = None) -> str:
    """A titled section without the closing frame (for long lists)."""
    selected = theme_for(theme)
    heading = sanitize(title).upper()
    if selected.compact:
        out = [f"{selected.accent} {heading}"]
        for line in _as_lines(lines):
            out.append(("  " + sanitize(line)).rstrip())
        return "\n".join(out)
    head = f"{selected.accent} {heading} "
    out = [head + selected.divider * max(4, selected.width - len(head) - 1)]
    for line in _as_lines(lines):
        for wrapped in _wrap(line, selected.width - 3):
            out.append(f"  {wrapped}")
    return "\n".join(out)


def panel(
    kind: str,
    title: str,
    lines=None,
    theme: Optional[str] = None,
    footer: Optional[str] = None,
) -> str:
    """Render a tagged status panel (ok/error/warn/info/run/done)."""
    selected = theme_for(theme)
    tag = selected.tags.get(kind, selected.tags["info"])
    body = _as_lines(lines)
    if selected.compact:
        out = [f"{tag} {sanitize(title).upper()}"]
        for line in body:
            out.append(("  " + sanitize(line)).rstrip())
        if footer:
            out.append(("  " + sanitize(footer)).rstrip())
        return "\n".join(out)
    return frame(f"{tag} {title}", body, footer=footer, theme=selected.key)


def success(title: str, lines=None, footer: Optional[str] = None) -> str:
    return panel("ok", title, lines, footer=footer)


def error(title: str, lines=None, footer: Optional[str] = None) -> str:
    return panel("error", title, lines, footer=footer)


def warning(title: str, lines=None, footer: Optional[str] = None) -> str:
    return panel("warn", title, lines, footer=footer)


def info(title: str, lines=None, footer: Optional[str] = None) -> str:
    return panel("info", title, lines, footer=footer)


def loading(title: str, lines=None, footer: Optional[str] = None) -> str:
    return panel("run", title, lines, footer=footer)


def done(title: str, lines=None, footer: Optional[str] = None) -> str:
    return panel("done", title, lines, footer=footer)


# ------------------------------------------------------------------- composing
def kv(pairs: Iterable[Tuple[str, object]], theme: Optional[str] = None) -> str:
    """Key/value block aligned for monospace-ish reading."""
    selected = theme_for(theme)
    rows = [(str(k), sanitize(v)) for k, v in pairs]
    if not rows:
        return ""
    label_width = min(max(len(k) for k, _ in rows), selected.width - 14)
    lead = "  " if selected.compact else ""
    out = []
    for key, value in rows:
        prefix = f"{lead}{selected.bullet} {key:<{label_width}}  "
        wrapped = _wrap(value, max(8, selected.width - len(prefix) - 1))
        out.append((prefix + wrapped[0]).rstrip())
        for extra in wrapped[1:]:
            out.append((" " * len(prefix) + extra).rstrip())
    return "\n".join(out)


def bullets(items: Iterable[object], theme: Optional[str] = None) -> str:
    selected = theme_for(theme)
    out = []
    lead = "  " if selected.compact else ""
    for item in items:
        wrapped = _wrap(str(item), max(8, selected.width - 3))
        if not wrapped:
            continue
        out.append(f"{lead}  {selected.bullet} {wrapped[0]}".rstrip())
        for extra in wrapped[1:]:
            out.append(f"{lead}    {extra}".rstrip())
    return "\n".join(out)


def table(headers: Sequence[str], rows: Sequence[Sequence[object]], theme: Optional[str] = None) -> str:
    """Minimal text table; column widths are clamped to the theme width."""
    selected = theme_for(theme)
    headers = [sanitize(h) for h in headers]
    cells = [[sanitize(c) for c in row] for row in rows]
    if not headers or not cells:
        return ""
    widths = []
    for index, header in enumerate(headers):
        column = [header] + [row[index] for row in cells if index < len(row)]
        widths.append(min(max(len(value) for value in column), max(10, selected.width // max(1, len(headers)))))
    header_line = "  ".join(h[: widths[i]].ljust(widths[i]) for i, h in enumerate(headers)).rstrip()
    out = [header_line, selected.divider * min(selected.width, len(header_line))]
    for row in cells:
        out.append(
            "  ".join(
                str(row[i] if i < len(row) else "")[: widths[i]].ljust(widths[i])
                for i in range(len(headers))
            ).rstrip()
        )
    return "\n".join(out)


def bar(percent: float, width: int = 18, filled: str = "█", empty: str = "░") -> str:
    """A textual progress bar that never exceeds its width."""
    try:
        value = float(percent)
    except (TypeError, ValueError):
        value = 0.0
    value = max(0.0, min(100.0, value))
    width = max(4, min(int(width), 40))
    done = int(round(width * value / 100.0))
    return f"[{filled * done}{empty * (width - done)}] {value:5.1f}%"


def progress(title: str, percent: float, detail: str = "", task_id: str = "", theme: Optional[str] = None) -> str:
    """Single-line progress render used while editing a message in place."""
    selected = theme_for(theme)
    head = f"{selected.tags['run']} {sanitize(title)}"
    parts = [head, bar(percent, 12 if selected.compact else 18)]
    if detail:
        parts.append(sanitize(detail))
    if task_id:
        parts.append(f"task {code(task_id)}")
    return "  ".join(parts)


def escape_for_caption(value: object) -> str:
    """Escape a short value for use inside a Telegram media caption."""
    text = escape_md(value)
    return text[: MAX_CAPTION_LENGTH - 1]


def compact_message(tag: str, title: str, detail: str = "") -> str:
    """One-line routine output for compact mode."""
    selected = theme_for("COMPACT")
    text = f"{selected.tags.get(tag, '[info]')} {sanitize(title)}"
    if detail:
        text += f"  {sanitize(detail)}"
    return text


# --------------------------------------------------------------------- preview
def preview(theme: Optional[str] = None) -> str:
    """Render a sample of every engine component (used by ``.preview``)."""
    selected = theme_for(theme)
    parts = [
        banner(selected.key),
        frame(
            "Message Engine",
            [
                "Theme: " + selected.label + "  (" + selected.description + ")",
                "Frames, tags, tables and progress all share one renderer.",
            ],
            footer="REZE 2.0 // " + __version__,
            theme=selected.key,
        ),
        section("Status tags", theme=selected.key),
        "\n".join(
            f"  {selected.tags[kind]}  {label}"
            for kind, label in (
                ("ok", "success"),
                ("error", "error"),
                ("warn", "warning"),
                ("info", "information"),
                ("run", "loading"),
                ("done", "completed"),
            )
        ),
        section("Alignment", theme=selected.key),
        kv([("owner", "UnchartedAli"), ("channel", "@yamods"), ("version", __version__)], theme=selected.key),
        section("Progress", theme=selected.key),
        progress("rendering preview", 62.5, "stage 2/3", "a1b2c3", theme=selected.key),
        section("Layout", theme=selected.key),
        table(["Command", "Scope"], [["theme", "appearance"], ["preview", "appearance"]], theme=selected.key),
        divider(selected.key),
        "Available themes: " + ", ".join(theme_names()),
        "Switch with .theme <name>",
    ]
    return "\n".join(part for part in parts if part)


def available_themes() -> str:
    return "\n".join(
        f"  {get_theme(name).accent} {name:<9} {get_theme(name).description}"
        for name in theme_names()
    )


__all__ = [
    "MAX_CAPTION_LENGTH",
    "MAX_MESSAGE_LENGTH",
    "THEMES",
    "active_theme_name",
    "available_themes",
    "banner",
    "bar",
    "bullets",
    "code",
    "compact_message",
    "divider",
    "done",
    "error",
    "escape_for_caption",
    "escape_md",
    "frame",
    "info",
    "kv",
    "loading",
    "panel",
    "preview",
    "progress",
    "sanitize",
    "section",
    "split_text",
    "success",
    "table",
    "theme_for",
    "theme_names",
    "warning",
]
