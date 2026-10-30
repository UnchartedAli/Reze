"""Writing DNA: learn a local, statistical profile of the user's writing.

This is deliberately transparent: it counts measurable features instead of
pretending to understand style. No text leaves the machine and no AI is needed.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

from reze.database import db
from reze.localization.manager import normalize

_WORD_RE = re.compile(r"[A-Za-z0-9_'\-]+|[\u0600-\u06ff\u200c]+", re.UNICODE)
_SENTENCE_RE = re.compile(r"[.!?؟…\n]+")
_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]",
    re.UNICODE,
)
_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "you", "are", "was", "have", "but",
    "not", "from", "they", "will", "would", "there", "their", "about", "what", "when",
    "و", "در", "به", "از", "که", "این", "را", "با", "برای", "است", "می", "شود", "های",
    "یک", "آن", "هم", "یا", "تا", "بر", "اما", "اگر", "چه", "نیز", "بود", "کرد",
}


def metrics(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    normalized = normalize(raw)
    words = _WORD_RE.findall(normalized)
    sentences = [part.strip() for part in _SENTENCE_RE.split(raw) if part.strip()]
    word_count = len(words)
    sentence_count = max(len(sentences), 1 if word_count else 0)
    lower_words = [word.lower() for word in words if len(word) > 2 and word.lower() not in _STOPWORDS]
    return {
        "chars": len(raw),
        "words": word_count,
        "sentences": sentence_count,
        "avg_sentence_words": round(word_count / sentence_count, 2) if sentence_count else 0.0,
        "avg_word_length": round(sum(len(word) for word in words) / word_count, 2) if word_count else 0.0,
        "question_ratio": round(raw.count("?") + raw.count("؟"), 3) / sentence_count if sentence_count else 0.0,
        "exclamation_ratio": round(raw.count("!") + raw.count("!"), 3) / sentence_count if sentence_count else 0.0,
        "emoji": len(_EMOJI_RE.findall(raw)),
        "persian_ratio": round(
            sum(1 for char in raw if "\u0600" <= char <= "\u06ff") / max(1, len(raw)), 3
        ),
        "top_words": Counter(lower_words).most_common(5),
    }


_METRIC_KEYS = ("avg_sentence_words", "avg_word_length", "question_ratio", "exclamation_ratio", "persian_ratio")


class WritingService:
    def add_sample(self, text: str, source: str = "manual") -> int:
        content = (text or "").strip()
        if len(content) < 20:
            raise ValueError("A writing sample needs at least 20 characters.")
        return db.execute(
            "INSERT INTO writing_samples (content, source) VALUES (?, ?)",
            (content[:20000], (source or "manual")[:40]),
        )

    def samples(self, limit: int = 50) -> List[Dict[str, Any]]:
        return db.query(
            "SELECT * FROM writing_samples ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )

    def profile(self) -> Dict[str, Any]:
        rows = self.samples(limit=100)
        if not rows:
            return {"samples": 0, "metrics": {}, "top_words": []}
        aggregate = {key: 0.0 for key in _METRIC_KEYS}
        top: Counter = Counter()
        for row in rows:
            item = metrics(row["content"])
            for key in _METRIC_KEYS:
                aggregate[key] += float(item.get(key) or 0)
            top.update(dict(item.get("top_words") or []))
        count = len(rows)
        return {
            "samples": count,
            "metrics": {key: round(value / count, 2) for key, value in aggregate.items()},
            "top_words": top.most_common(10),
        }

    def analyze(self, text: str) -> Dict[str, Any]:
        current = metrics(text)
        profile = self.profile()
        baseline = profile.get("metrics") or {}
        deviations = {}
        for key in _METRIC_KEYS:
            expected = float(baseline.get(key) or 0)
            actual = float(current.get(key) or 0)
            scale = max(1.0, abs(expected))
            deviations[key] = round((actual - expected) / scale, 2)
        score = 0
        if baseline:
            penalty = sum(min(abs(value), 1.0) for value in deviations.values()) / len(deviations)
            score = round(max(0.0, 100 - penalty * 100), 0)
        return {"metrics": current, "profile": profile, "deviations": deviations, "similarity": int(score)}

    def count(self) -> int:
        row = db.query_one("SELECT COUNT(*) AS total FROM writing_samples")
        return int((row or {}).get("total") or 0)


writing_service = WritingService()

__all__ = ["WritingService", "metrics", "writing_service"]
