"""Deterministic writing-style profile. No AI, no I/O: fully testable.

Only the owner's own messages are passed in. The profile holds aggregate
numbers and a few short phrases; it does not hold full messages.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Sequence

MIN_SAMPLES_FOR_STYLE = 5
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_PERSIAN_RE = re.compile(r"[\u0600-\u06FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_WORD_RE = re.compile(r"[\w\u0600-\u06FF']+")


def _share(count: int, total: int) -> float:
    return round(count / total, 3) if total else 0.0


def analyze(samples: Sequence[str]) -> Dict[str, Any]:
    """Aggregate statistics over the owner's messages. Empty input yields a count of 0."""
    texts = [text.strip() for text in samples if text and text.strip()]
    total = len(texts)
    if total == 0:
        return {"count": 0}
    words = [len(_WORD_RE.findall(text)) for text in texts]
    chars = [len(text) for text in texts]
    persian = sum(len(_PERSIAN_RE.findall(text)) for text in texts)
    latin = sum(len(_LATIN_RE.findall(text)) for text in texts)
    script_total = persian + latin
    openers: Counter = Counter()
    closers: Counter = Counter()
    emojis: Counter = Counter()
    for text in texts:
        tokens = _WORD_RE.findall(text)
        if tokens:
            openers[tokens[0].lower()] += 1
            closers[tokens[-1].lower()] += 1
        emojis.update(_EMOJI_RE.findall(text))
    return {
        "count": total,
        "median_words": sorted(words)[total // 2],
        "median_chars": sorted(chars)[total // 2],
        "persian_share": _share(persian, script_total),
        "emoji_share": _share(sum(1 for t in texts if _EMOJI_RE.search(t)), total),
        "question_share": _share(sum(1 for t in texts if "?" in t or "؟" in t), total),
        "exclamation_share": _share(sum(1 for t in texts if "!" in t), total),
        "ends_with_period_share": _share(sum(1 for t in texts if t.endswith(".")), total),
        "lowercase_start_share": _share(sum(1 for t in texts if t[:1].islower()), total),
        "top_openers": [word for word, _ in openers.most_common(5) if word],
        "top_closers": [word for word, _ in closers.most_common(5) if word],
        "top_emojis": [emoji for emoji, _ in emojis.most_common(5)],
    }


def describe(profile: Dict[str, Any], language: str = "en") -> List[str]:
    """Short human-readable lines about the profile."""
    fa = language == "fa"
    count = int(profile.get("count", 0))
    if count < MIN_SAMPLES_FOR_STYLE:
        return [
            (f"داده کافی نیست ({count} پیام؛ حداقل {MIN_SAMPLES_FOR_STYLE} لازم است)."
             if fa else
             f"Not enough data yet ({count} messages; at least {MIN_SAMPLES_FOR_STYLE} needed).")
        ]
    lines = []
    if fa:
        lines.append(f"میانهٔ طول پیام: {profile['median_words']} کلمه")
        lines.append(f"سهم متن فارسی: {round(profile['persian_share'] * 100)}٪")
        lines.append(f"سهم پیام‌های دارای ایموجی: {round(profile['emoji_share'] * 100)}٪")
        if profile["top_openers"]:
            lines.append("شروع‌های رایج: " + "، ".join(profile["top_openers"][:3]))
        if profile["top_emojis"]:
            lines.append("ایموجی‌های رایج: " + " ".join(profile["top_emojis"]))
    else:
        lines.append(f"Median length: {profile['median_words']} words")
        lines.append(f"Persian share: {round(profile['persian_share'] * 100)}%")
        lines.append(f"Messages with emoji: {round(profile['emoji_share'] * 100)}%")
        if profile["top_openers"]:
            lines.append("Common openers: " + ", ".join(profile["top_openers"][:3]))
        if profile["top_emojis"]:
            lines.append("Common emoji: " + " ".join(profile["top_emojis"]))
    return lines


def select_examples(samples: Sequence[str], limit: int = 12, max_chars: int = 200) -> List[str]:
    """A few of the owner's most recent messages, trimmed, as examples for the model."""
    picked = [text.strip()[:max_chars] for text in samples if text and text.strip()]
    return picked[-limit:]


__all__ = ["MIN_SAMPLES_FOR_STYLE", "analyze", "describe", "select_examples"]
