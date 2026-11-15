"""Digest text: links, Telegram-safe splitting, grounding checks, basic summary, rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from reze.digest.models import ChannelBatch, ChannelSection, SourceMessage
from reze.localization.normalize import normalize
from reze.ui import ascii

#: Telegram counts UTF-16 units (limit 4096). A Python character is at most two
#: units, so 2000 characters per chunk stays under the limit with headroom.
TELEGRAM_CHUNK_CHARS = 2000

LABELS = {
    "en": {
        "title": "📬 REZE DIGEST",
        "date": "📅 Date",
        "period": "🕘 Period",
        "highlights": "🔥 Top Highlights",
        "channels": "📡 Channel Summaries",
        "links": "🔗 Original messages",
        "overview": "📊 Daily Overview",
        "checked": "Channels checked",
        "processed": "Messages processed",
        "important": "Important messages",
        "mode": "Summary",
        "omitted": "more item(s) not shown because of the length limit",
        "dropped": "AI statements removed because they could not be verified",
        "ai": "AI summary",
        "basic": "Basic summary (AI is off)",
        "ai_fallback": "Basic summary (AI was unavailable)",
        "nothing": "No new posts",
        "ai_limit": "post(s) not sent to the AI because of the input limit",
        "basic_omitted": "post(s) not shown in the basic summary",
    },
    "fa": {
        "title": "📬 گزارش REZE",
        "date": "📅 تاریخ",
        "period": "🕘 بازه",
        "highlights": "🔥 مهم‌ترین موارد",
        "channels": "📡 خلاصهٔ کانال‌ها",
        "links": "🔗 پیام‌های اصلی",
        "overview": "📊 مرور کلی",
        "checked": "کانال‌های بررسی‌شده",
        "processed": "پیام‌های پردازش‌شده",
        "important": "پیام‌های مهم",
        "mode": "روش خلاصه‌سازی",
        "omitted": "مورد دیگر به دلیل محدودیت طول نمایش داده نشد",
        "dropped": "جمله‌های هوش مصنوعی که تأیید نشدند حذف شدند",
        "ai": "خلاصهٔ هوش مصنوعی",
        "basic": "خلاصهٔ ساده (هوش مصنوعی خاموش است)",
        "ai_fallback": "خلاصهٔ ساده (هوش مصنوعی در دسترس نبود)",
        "nothing": "پست جدیدی نبود",
        "ai_limit": "پست به‌دلیل محدودیت ورودی هوش مصنوعی برای خلاصه ارسال نشد",
        "basic_omitted": "پست در خلاصهٔ ساده نمایش داده نشد",
    },
}

_URL_RE = re.compile(r"https?://[^\s<>\"'()]+")
_NUMBER_RE = re.compile(r"\d+(?:[.,/:-]\d+)*")
_KEEP_FA_RLM = "\u200f"


def message_link(chat_id: int, username: str, message_id: int) -> Optional[str]:
    """Public link for a channel post, or None when Telegram gives no usable link."""
    if not message_id:
        return None
    if username:
        return f"https://t.me/{username}/{message_id}"
    text = str(chat_id)
    if chat_id < 0 and text.startswith("-100") and len(text) > 4:
        return f"https://t.me/c/{text[4:]}/{message_id}"
    return None


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def split_for_telegram(text: str) -> List[str]:
    """Split a digest into Telegram-safe chunks without dropping content.

    Reuses the project's splitter, which keeps lines whole where it can and
    preserves order. Only leading spaces at a hard split point are removed.
    """
    if not (text or "").strip():
        return []
    chunks = ascii.split_text(text, TELEGRAM_CHUNK_CHARS)
    return [chunk for chunk in chunks if chunk.strip()]


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?)]}")


def tokens_of(text: str) -> set:
    """Numbers and links in *text*, after Persian and Arabic digits are normalized."""
    normalized = normalize(text)
    urls = {_clean_url(url) for url in _URL_RE.findall(normalized)}
    urls.discard("")
    numbers = set(_NUMBER_RE.findall(normalized))
    return urls | numbers


def unsupported_tokens(statement: str, sources: Iterable[str]) -> List[str]:
    """Numbers and links in *statement* that do not appear in the source posts.

    This is the grounding check. A statement with any unsupported token is not
    trusted and is removed from the AI output.
    """
    blob = normalize("\n".join(source or "" for source in sources))
    missing = []
    for token in sorted(tokens_of(statement)):
        if token.startswith("http"):
            if token not in blob:
                missing.append(token)
        elif not re.search(rf"(?<!\d){re.escape(token)}(?!\d)", blob):
            missing.append(token)
    return missing


def clean_text(text: str, limit: int = 280) -> str:
    flat = " ".join((text or "").split())
    if len(flat) > limit:
        flat = flat[: max(1, limit - 1)].rstrip() + "…"
    return flat


def matches_keywords(text: str, include_csv: str, exclude_csv: str) -> bool:
    """Case-insensitive keyword filter. Include list must match when set; exclude list must not."""
    haystack = normalize(text or "").lower()
    includes = [word.strip().lower() for word in (include_csv or "").split(",") if word.strip()]
    excludes = [word.strip().lower() for word in (exclude_csv or "").split(",") if word.strip()]
    if includes and not any(word in haystack for word in includes):
        return False
    if any(word in haystack for word in excludes):
        return False
    return True


def score_message(message: SourceMessage) -> int:
    """Heuristic importance: numbers, dates, links and substance rank higher than chatter."""
    text = message.text or ""
    score = 0
    if _NUMBER_RE.search(normalize(text)):
        score += 2
    if _URL_RE.search(text):
        score += 2
    if len(text) > 120:
        score += 1
    if message.is_forward:
        score -= 1
    return score


def basic_sections(
    batches: Sequence[ChannelBatch],
    per_channel: int = 6,
    highlights: int = 4,
) -> Tuple[List[str], List[ChannelSection]]:
    """Non-AI digest: the best posts per channel, chosen by score then recency."""
    ordered = sorted(batches, key=lambda batch: (batch.priority, batch.title))
    sections: List[ChannelSection] = []
    ranked_overall: List[Tuple[int, int, int, str]] = []
    for batch in ordered:
        messages = [m for m in batch.messages if (m.text or "").strip()]
        if not messages:
            continue
        ranked = sorted(messages, key=lambda m: (score_message(m), m.date), reverse=True)
        chosen = ranked[:per_channel]
        bullets = []
        for message in chosen:
            prefix = "(forwarded) " if message.is_forward else ""
            bullets.append(prefix + clean_text(message.text, 240))
        links = [m.link for m in sorted(chosen, key=lambda m: m.message_id) if m.link][:3]
        sections.append(ChannelSection(title=batch.title, bullets=bullets, links=links))
        for message in chosen:
            ranked_overall.append((score_message(message), -batch.priority, message.message_id, clean_text(message.text, 200)))
    ranked_overall.sort(reverse=True)
    overall = [item[3] for item in ranked_overall[:highlights]]
    return overall, sections


@dataclass
class RenderStats:
    channels_checked: int
    messages_processed: int
    important_messages: int
    mode: str


def render_digest(
    *,
    language: str,
    date_label: str,
    period_label: str,
    overall: List[str],
    sections: List[ChannelSection],
    stats: RenderStats,
    notes: List[str],
    max_chars: int,
) -> str:
    """Build the digest text.

    Headings, the overview and notes are always kept. Bullets are added in order
    until the length limit is reached; every bullet that does not fit is counted
    and reported in the overview, so nothing is dropped silently.
    """
    labels = LABELS.get(language, LABELS["en"])
    rtl = _KEEP_FA_RLM if language == "fa" else ""
    header_lines = [
        f"{rtl}{labels['title']}",
        f"{labels['date']}: {date_label}",
        f"{labels['period']}: {period_label}",
    ]
    overview_lines = [
        f"{rtl}{labels['overview']}",
        f"- {labels['checked']}: {stats.channels_checked}",
        f"- {labels['processed']}: {stats.messages_processed}",
        f"- {labels['important']}: {stats.important_messages}",
        f"- {labels['mode']}: {_mode_label(stats.mode, labels)}",
    ]
    overview_lines.extend(f"- {note}" for note in notes)
    footer_text = "\n".join(overview_lines)
    header_text = "\n".join(header_lines)

    # Groups: (heading lines, bullet lines, optional trailer lines).
    groups: List[Tuple[List[str], List[str], List[str]]] = []
    if overall:
        groups.append(([f"{rtl}{labels['highlights']}"], [f"- {item}" for item in overall], []))
    for index, section in enumerate(sections):
        heading = [f"{rtl}{labels['channels']}", section.title] if index == 0 else [section.title]
        bullets = [f"- {bullet}" for bullet in section.bullets]
        trailer = []
        if section.links:
            trailer = [f"  {labels['links']}: " + "  ".join(section.links)]
        groups.append((heading, bullets, trailer))

    budget = max(200, int(max_chars) - len(header_text) - len(footer_text) - 200)
    body: List[str] = []
    used = 0

    def try_add(lines: List[str]) -> bool:
        nonlocal used
        cost = sum(len(line) + 1 for line in lines)
        if used + cost > budget:
            return False
        body.extend(lines)
        used += cost
        return True

    omitted = 0
    exhausted_at: Optional[int] = None
    for position, (heading, bullets, trailer) in enumerate(groups):
        emitted_heading = False
        for index, bullet in enumerate(bullets):
            extra = [] if emitted_heading else heading
            if try_add(extra + [bullet]):
                emitted_heading = True
                continue
            omitted += len(bullets) - index
            exhausted_at = position
            break
        if exhausted_at is not None:
            break
        if emitted_heading:
            if trailer:
                try_add(trailer)  # links are optional and carry no content of their own
            try_add([""])
    if exhausted_at is not None:
        for _, bullets, _ in groups[exhausted_at + 1 :]:
            omitted += len(bullets)

    overview = footer_text
    if omitted:
        overview = overview + f"\n- {omitted} {labels['omitted']}"
    parts = [header_text, ""] + body + [overview]
    return "\n".join(parts).strip("\n") + "\n"


def _mode_label(mode: str, labels: dict) -> str:
    return {
        "ai": labels["ai"],
        "basic": labels["basic"],
        "ai_fallback_basic": labels["ai_fallback"],
    }.get(mode, mode)


def period_label(start, end, tz_name: str) -> str:
    """Human period label in the configured timezone, for example '09:00 — 21:00'."""
    from zoneinfo import ZoneInfo
    from datetime import timezone as _tz

    if start is None or end is None:
        return "—"
    zone = ZoneInfo(tz_name)
    left = start.replace(tzinfo=_tz.utc).astimezone(zone)
    right = end.replace(tzinfo=_tz.utc).astimezone(zone)
    return f"{left:%Y-%m-%d %H:%M} — {right:%Y-%m-%d %H:%M} ({tz_name})"


__all__ = [
    "LABELS",
    "RenderStats",
    "TELEGRAM_CHUNK_CHARS",
    "basic_sections",
    "clean_text",
    "matches_keywords",
    "message_link",
    "period_label",
    "render_digest",
    "score_message",
    "split_for_telegram",
    "tokens_of",
    "unsupported_tokens",
    "utf16_len",
]
