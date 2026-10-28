"""
Visual themes for the Reze Extreme-ASCII message engine.

Four built-in themes share one glyph contract, so every command renders through
the same renderer and only the frame changes:

``CYBER``     heavy double-line frames, diamond accents (default identity)
``GHOST``     light single-line frames, dot accents
``TERMINAL``  pure ASCII frames for clients with poor box-drawing support
``COMPACT``   no frames at all: one line per entry, tuned for narrow phones

None of the glyphs use characters that Telegram's Markdown parser treats as
formatting (``_ * [ ] ` ~``), so theme output is safe to send unescaped while
user-controlled values are still escaped by the renderer.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    description: str
    width: int
    tl: str
    tr: str
    bl: str
    br: str
    h: str
    v: str
    lt: str
    rt: str
    accent: str
    bullet: str
    arrow: str
    divider: str
    tags: Dict[str, str] = field(default_factory=dict)
    compact: bool = False
    banner_style: str = "block"


_STANDARD_TAGS = {
    "ok": "[ OK ]",
    "error": "[FAIL]",
    "warn": "[WARN]",
    "info": "[INFO]",
    "run": "[ .. ]",
    "done": "[DONE]",
}

_COMPACT_TAGS = {
    "ok": "[ok]",
    "error": "[err]",
    "warn": "[warn]",
    "info": "[info]",
    "run": "[run]",
    "done": "[done]",
}


THEMES: Dict[str, Theme] = {
    "CYBER": Theme(
        key="CYBER",
        label="Cyber",
        description="Heavy double-line frames with diamond accents.",
        width=40,
        tl="╔", tr="╗", bl="╚", br="╝",
        h="═", v="║", lt="╠", rt="╣",
        accent="◆",
        bullet="▸",
        arrow="→",
        divider="─",
        tags=dict(_STANDARD_TAGS),
    ),
    "GHOST": Theme(
        key="GHOST",
        label="Ghost",
        description="Light single-line frames with dot accents.",
        width=40,
        tl="┌", tr="┐", bl="└", br="┘",
        h="─", v="│", lt="├", rt="┤",
        accent="░",
        bullet="·",
        arrow="→",
        divider="┄",
        tags=dict(_STANDARD_TAGS),
    ),
    "TERMINAL": Theme(
        key="TERMINAL",
        label="Terminal",
        description="Plain ASCII frames for maximum client compatibility.",
        width=40,
        tl="+", tr="+", bl="+", br="+",
        h="-", v="|", lt="+", rt="+",
        accent=">",
        bullet="*",
        arrow="->",
        divider="-",
        tags=dict(_STANDARD_TAGS),
    ),
    "COMPACT": Theme(
        key="COMPACT",
        label="Compact",
        description="Frameless layout tuned for narrow mobile screens.",
        width=30,
        tl="", tr="", bl="", br="",
        h="", v="", lt="", rt="",
        accent="›",
        bullet="•",
        arrow="->",
        divider="",
        tags=dict(_COMPACT_TAGS),
        compact=True,
        banner_style="line",
    ),
}

DEFAULT_THEME = "CYBER"


def get_theme(name: str = "") -> Theme:
    """Return a theme by name, falling back to the default for unknown values."""
    key = (name or DEFAULT_THEME).strip().upper()
    return THEMES.get(key, THEMES[DEFAULT_THEME])


def theme_names() -> list:
    return sorted(THEMES)
