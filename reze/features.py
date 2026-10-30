"""
Optional-feature switches for REZE 3.0.

Global policy implemented here: **every optional feature is OFF by default**.
Nothing starts on installation, after a restart, after a migration or after a
configuration reset. A missing row means OFF, an unreadable value means OFF and
enabling one feature never enables another.

Sensitive features (they send data to third parties, touch encrypted material,
act in the background or message other people) additionally require an explicit
confirmation at the call site; :class:`FeatureConfirmationRequired` is raised
otherwise. Essential security checks are not features and are never gated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from reze.database import db
from reze.logging_config import logger


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    description: str
    category: str = "Personal"
    sensitive: bool = False
    #: Localized (Persian) label/description, used when language = fa.
    label_fa: str = ""
    description_fa: str = ""


class FeatureConfirmationRequired(Exception):
    """Raised when a sensitive feature is enabled without explicit confirmation."""


class UnknownFeature(KeyError):
    """Raised for a feature key that does not exist."""


FEATURES: List[Feature] = [
    # ------------------------------------------------------------------ knowledge
    Feature(
        "memory",
        "AI Brain & memory",
        "Persistent notes the AI can recall, with tags, sources and search.",
        "Knowledge",
        label_fa="حافظه و مغز هوش مصنوعی",
        description_fa="یادداشت‌های ماندگار برای یادآوری توسط هوش مصنوعی، با برچسب و جستجو.",
    ),
    Feature(
        "life_graph",
        "Life Graph",
        "People, projects, places and topics connected by typed relations.",
        "Knowledge",
        label_fa="گراف زندگی",
        description_fa="اتصال افراد، پروژه‌ها، مکان‌ها و موضوع‌ها با رابطه‌های مشخص.",
    ),
    Feature(
        "crm",
        "Personal CRM",
        "Contacts, interaction history, birthdays and relationship reminders.",
        "Personal",
        label_fa="مدیریت ارتباطات",
        description_fa="مخاطبان، تاریخ تعامل‌ها، تولدها و یادآور ارتباط.",
    ),
    Feature(
        "decisions",
        "Decision journal",
        "Record decisions, expected outcomes and review them later.",
        "Personal",
        label_fa="دفتر تصمیم‌ها",
        description_fa="ثبت تصمیم‌ها، نتیجهٔ انتظاری و بازبینی بعدی.",
    ),
    Feature(
        "focus",
        "Focus Mode",
        "Timed focus sessions with a do-not-disturb window and statistics.",
        "Personal",
        label_fa="حالت تمرکز",
        description_fa="جلسه‌های تمرکز زمان‌دار با حالت مزاحمت‌نشدن و آمار.",
    ),
    Feature(
        "timeline",
        "Timeline",
        "One chronological stream of everything that happened in REZE.",
        "Knowledge",
        label_fa="خط زمانی",
        description_fa="جریان زمانی یکپارچه از همهٔ رویدادهای رِزه.",
    ),
    Feature(
        "writing_dna",
        "Writing DNA",
        "Learn your writing style from samples and check new text against it.",
        "Knowledge",
        label_fa="دی‌ان‌ای نوشتار",
        description_fa="یادگیری سبک نوشتار شما از نمونه‌ها و بررسی متن جدید.",
    ),
    Feature(
        "projects",
        "Projects & tasks",
        "Projects, tasks, priorities and due dates without a cloud service.",
        "Productivity",
        label_fa="پروژه‌ها و کارها",
        description_fa="پروژه، کار، اولویت و سررسید بدون سرویس ابری.",
    ),
    Feature(
        "expenses",
        "Expense tracking",
        "Local expense log with categories and monthly summaries.",
        "Productivity",
        label_fa="ثبت هزینه",
        description_fa="ثبت محلی هزینه با دسته‌بندی و خلاصهٔ ماهانه.",
    ),
    # ------------------------------------------------------------------ automation
    Feature(
        "workflows",
        "Persistent workflows",
        "Multi-step workflows with retries, idempotency keys and history.",
        "Automation",
        sensitive=True,
        label_fa="گردش‌کارهای ماندگار",
        description_fa="گردش‌کار چندمرحله‌ای با تلاش مجدد، کلید یکتایی و تاریخچه.",
    ),
    Feature(
        "random_reactions",
        "Random reactions",
        "React to a small share of incoming messages in chats you choose.",
        "Automation",
        sensitive=True,
        label_fa="واکنش‌های تصادفی",
        description_fa="واکنش به درصدی از پیام‌های چت‌های انتخابی شما.",
    ),
    Feature(
        "background_monitoring",
        "Background monitoring",
        "Master switch for background loops (scheduler, sentinel, inbox).",
        "Automation",
        sensitive=True,
        label_fa="پایش پس‌زمینه",
        description_fa="کلید اصلی حلقه‌های پس‌زمینه (زمان‌بند، نگهبان، صندوق ورودی).",
    ),
    # -------------------------------------------------------------------- privacy
    Feature(
        "vault",
        "Digital Vault",
        "Encrypted secrets and files, unlocked only for the owner.",
        "Security",
        sensitive=True,
        label_fa="گاوصندوق دیجیتال",
        description_fa="رمزها و فایل‌های رمزگذاری‌شده، فقط برای مالک.",
    ),
    Feature(
        "security_sentinel",
        "Security Sentinel",
        "Proactive local security checks and owner notifications.",
        "Security",
        sensitive=True,
        label_fa="نگهبان امنیت",
        description_fa="بررسی‌های امنیتی محلی و اطلاع‌رسانی به مالک.",
    ),
    Feature(
        "self_maintenance",
        "Self-maintenance",
        "Integrity checks, pruning, retention and safe backups.",
        "Security",
        label_fa="نگهداری خودکار",
        description_fa="بررسی سلامت، پاک‌سازی، نگهداری و پشتیبان‌گیری امن.",
    ),
    Feature(
        "bot_companion",
        "Telegram Bot Companion",
        "Optional bot that opens an inline settings menu for the owner only.",
        "Security",
        sensitive=True,
        label_fa="ربات همراه تلگرام",
        description_fa="ربات اختیاری با منوی تنظیمات درون‌خطی، فقط برای مالک.",
    ),
    # ------------------------------------------------------------------------ AI
    Feature(
        "ai_agent",
        "AI Agent & tool calling",
        "Let the AI propose allowed tools; approvals are always required.",
        "AI",
        sensitive=True,
        label_fa="عامل هوش مصنوعی و فراخوانی ابزار",
        description_fa="پیشنهاد ابزارهای مجاز توسط هوش مصنوعی؛ تأیید همیشه لازم است.",
    ),
    Feature(
        "model_council",
        "Model Council",
        "Ask several configured models and synthesize one answer.",
        "AI",
        sensitive=True,
        label_fa="شورای مدل‌ها",
        description_fa="پرسش از چند مدل و ساخت یک پاسخ نهایی.",
    ),
    Feature(
        "insights",
        "Insight Engine",
        "Local statistics and optional AI narratives about your week.",
        "AI",
        label_fa="موتور بینش",
        description_fa="آمار محلی و روایت اختیاری هوش مصنوعی دربارهٔ هفتهٔ شما.",
    ),
    # -------------------------------------------------------------------- capture
    Feature(
        "smart_inbox",
        "Smart Inbox",
        "Prioritize incoming messages locally; it never replies on its own.",
        "Capture",
        sensitive=True,
        label_fa="صندوق ورودی هوشمند",
        description_fa="اولویت‌بندی پیام‌های ورودی به‌صورت محلی؛ هرگز خودکار پاسخ نمی‌دهد.",
    ),
    Feature(
        "universal_search",
        "Universal Search",
        "Search memories, notes, CRM, decisions and documents with FTS5.",
        "Capture",
        label_fa="جستجوی یکپارچه",
        description_fa="جستجو در حافظه، یادداشت‌ها، ارتباطات، تصمیم‌ها و اسناد با FTS5.",
    ),
    Feature(
        "voice_intelligence",
        "Voice intelligence",
        "Transcribe voice notes through an OpenAI-compatible provider.",
        "Capture",
        sensitive=True,
        label_fa="هوشمندی صدا",
        description_fa="تبدیل ویس به متن با ارائه‌دهندهٔ سازگار با OpenAI.",
    ),
    Feature(
        "document_intelligence",
        "Document intelligence",
        "Extract text from DOCX/PDF/text files and summarize or index it.",
        "Capture",
        sensitive=True,
        label_fa="هوشمندی اسناد",
        description_fa="استخراج متن از DOCX/PDF/متن و خلاصه یا نمایه‌سازی آن.",
    ),
]

_BY_KEY: Dict[str, Feature] = {feature.key: feature for feature in FEATURES}


def feature_spec(key: str) -> Feature:
    try:
        return _BY_KEY[(key or "").strip().lower()]
    except KeyError as exc:
        raise UnknownFeature(f"Unknown feature: {key}") from exc


class FeatureStore:
    """Database-backed feature switches. Missing = OFF, always."""

    def __init__(self) -> None:
        self._cache: Dict[str, bool] = {}

    # ------------------------------------------------------------------- reading
    def is_enabled(self, key: str) -> bool:
        normalized = (key or "").strip().lower()
        if normalized not in _BY_KEY:
            return False
        if normalized in self._cache:
            return self._cache[normalized]
        try:
            row = db.query_one(
                "SELECT enabled FROM feature_state WHERE key = ?", (normalized,)
            )
        except Exception:  # pragma: no cover - database unavailable
            return False
        value = bool(row and int(row.get("enabled") or 0) == 1)
        self._cache[normalized] = value
        return value

    def enabled_keys(self) -> List[str]:
        return [feature.key for feature in FEATURES if self.is_enabled(feature.key)]

    def disabled_keys(self) -> List[str]:
        return [feature.key for feature in FEATURES if not self.is_enabled(feature.key)]

    # ------------------------------------------------------------------- writing
    def set_enabled(
        self,
        key: str,
        enabled: bool,
        actor: int = 0,
        confirmed: bool = False,
    ) -> bool:
        spec = feature_spec(key)
        if enabled and spec.sensitive and not confirmed:
            raise FeatureConfirmationRequired(
                f"'{spec.label}' is sensitive. Confirm explicitly to enable it."
            )
        db.execute(
            "INSERT INTO feature_state (key, enabled, updated_by, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET enabled = excluded.enabled, "
            "updated_by = excluded.updated_by, updated_at = CURRENT_TIMESTAMP",
            (spec.key, 1 if enabled else 0, int(actor or 0)),
        )
        self._cache[spec.key] = bool(enabled)
        self._audit(spec, enabled, actor)
        logger.info("Feature '%s' %s", spec.key, "enabled" if enabled else "disabled")
        return bool(enabled)

    def enable(self, key: str, actor: int = 0, confirmed: bool = False) -> bool:
        return self.set_enabled(key, True, actor=actor, confirmed=confirmed)

    def disable(self, key: str, actor: int = 0) -> bool:
        self.set_enabled(key, False, actor=actor, confirmed=True)
        return True

    def toggle(self, key: str, actor: int = 0, confirmed: bool = False) -> bool:
        if self.is_enabled(key):
            self.disable(key, actor=actor)
            return False
        return self.enable(key, actor=actor, confirmed=confirmed)

    def _audit(self, spec: Feature, enabled: bool, actor: int) -> None:
        try:
            db.execute(
                "INSERT INTO audit_log (actor, action, target, detail, outcome) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    int(actor or 0),
                    "feature.enable" if enabled else "feature.disable",
                    spec.key,
                    spec.label,
                    "sensitive" if spec.sensitive else "standard",
                ),
            )
        except Exception:  # pragma: no cover - auditing must not block the change
            pass

    # ------------------------------------------------------------------- reporting
    def snapshot(self, language: str = "en") -> List[Dict[str, Any]]:
        rows = []
        for feature in FEATURES:
            enabled = self.is_enabled(feature.key)
            label = feature.label_fa if language == "fa" and feature.label_fa else feature.label
            description = (
                feature.description_fa
                if language == "fa" and feature.description_fa
                else feature.description
            )
            rows.append(
                {
                    "key": feature.key,
                    "label": label,
                    "description": description,
                    "category": feature.category,
                    "sensitive": feature.sensitive,
                    "enabled": enabled,
                    "state": "ON" if enabled else "OFF",
                }
            )
        return rows

    def summary(self) -> Dict[str, Any]:
        enabled = self.enabled_keys()
        return {
            "total": len(FEATURES),
            "enabled": len(enabled),
            "enabled_keys": enabled,
            "all_off": not enabled,
        }

    def invalidate(self) -> None:
        self._cache.clear()


features = FeatureStore()


def is_enabled(key: str) -> bool:
    return features.is_enabled(key)


def require(key: str) -> Optional[str]:
    """Return a user-facing hint when *key* is OFF, otherwise ``None``."""
    if features.is_enabled(key):
        return None
    spec = feature_spec(key)
    return (
        f"{spec.label} is OFF by default. Enable it with: "
        f".features enable {spec.key}"
        + (" confirm" if spec.sensitive else "")
    )


__all__ = [
    "FEATURES",
    "Feature",
    "FeatureConfirmationRequired",
    "FeatureStore",
    "UnknownFeature",
    "feature_spec",
    "features",
    "is_enabled",
    "require",
]
