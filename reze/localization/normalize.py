"""Persian text normalization and Persian/Arabic digit handling."""

from __future__ import annotations

import re
import unicodedata

# Arabic characters that Persian writers frequently substitute for the
# canonical Persian letters.
_CHAR_MAP = {
    "\u064a": "\u06cc",  # ARABIC YEH -> FARSI YEH
    "\u0649": "\u06cc",  # ALEF MAKSURA -> FARSI YEH
    "\u0643": "\u06a9",  # ARABIC KAF -> KEHEH
    "\u0629": "\u0647",  # TEH MARBUTA -> HEH
    "\u06c0": "\u0647",  # HEH WITH YEH ABOVE -> HEH
    "\u0640": "",        # TATWEEL
    "\u200e": "",        # LRM
    "\u200f": "",        # RLM (kept out of stored text; direction is applied per message)
    "\u202a": "",
    "\u202b": "",
    "\u202c": "",
    "\u202d": "",
    "\u202e": "",
}

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {ord(char): str(index) for index, char in enumerate(_PERSIAN_DIGITS)}
_DIGIT_MAP.update({ord(char): str(index) for index, char in enumerate(_ARABIC_DIGITS)})

_DIACRITICS_RE = re.compile(r"[\u064b-\u065f\u0670]")
_SPACES_RE = re.compile(r"[ \t\u00a0\u2000-\u200a]+")
_ZWNJ = "\u200c"

#: Characters that may not survive a round trip through some terminals.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize(text: str) -> str:
    """Normalize Persian text for storage and comparison.

    * unifies Arabic/Persian letter variants and removes diacritics/tatweel;
    * converts Persian and Arabic-Indic digits to ASCII digits;
    * collapses horizontal whitespace and trims;
    * keeps ZWNJ (it is meaningful in Persian) but removes bidi controls.
    """
    if not text:
        return ""
    value = unicodedata.normalize("NFC", str(text))
    value = _CONTROL_RE.sub("", value)
    for source, target in _CHAR_MAP.items():
        value = value.replace(source, target)
    value = _DIACRITICS_RE.sub("", value)
    value = value.translate(_DIGIT_MAP)
    value = _SPACES_RE.sub(" ", value)
    return value.strip()


def has_persian(text: str) -> bool:
    """True when the text contains at least one Persian/Arabic letter."""
    return any("\u0600" <= char <= "\u06ff" for char in (text or ""))


def with_zwnj(text: str) -> str:
    """Join words with a zero-width non-joiner (used by the tests/help)."""
    return _ZWNJ.join(str(text).split())
