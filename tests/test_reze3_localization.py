"""Persian normalization, Jalali dates and the fa/en catalogs."""

import datetime
import json
import unittest
from pathlib import Path

import support  # noqa: F401  - prepares the database before reze imports

from reze.localization import (
    LANGUAGES,
    LanguageError,
    direction,
    format_date,
    get_language,
    is_rtl,
    normalize,
    set_language,
    t,
    to_jalali,
)
from reze.localization.manager import LOCALE_DIR, detect_language, rtl_wrap
from reze.localization.normalize import has_persian

FA = "فارسی"


class NormalizationTests(unittest.TestCase):
    def test_arabic_letters_are_unified(self):
        self.assertEqual(normalize("علي"), normalize("علی"))
        self.assertEqual(normalize("كتاب"), normalize("کتاب"))
        self.assertNotIn("\u064a", normalize("علي"))

    def test_digits_are_ascii(self):
        self.assertEqual(normalize("۱۲۳۴۵۶۷۸۹۰"), "1234567890")
        self.assertEqual(normalize("٠١٢٣٤٥٦٧٨٩"), "0123456789")

    def test_diacritics_and_bidi_controls_are_removed(self):
        self.assertEqual(normalize("مَتن"), "متن")
        self.assertEqual(normalize("\u200fمتن\u200e"), "متن")
        self.assertNotIn("\u200f", normalize("سلام"))
        self.assertEqual(normalize("a\u200cb"), "a\u200cb")  # ZWNJ is meaningful

    def test_whitespace_is_collapsed(self):
        self.assertEqual(normalize("  دو   کلمه  "), "دو کلمه")

    def test_detection_and_rtl_helpers(self):
        self.assertTrue(has_persian(FA))
        self.assertEqual(detect_language("سلام دنیا"), "fa")
        self.assertEqual(detect_language("hello"), "en")
        self.assertEqual(direction("fa"), "rtl")
        self.assertEqual(direction("en"), "ltr")
        self.assertTrue(is_rtl("fa-IR"))
        self.assertFalse(is_rtl("en"))


class JalaliTests(unittest.TestCase):
    def test_known_conversions(self):
        self.assertEqual(to_jalali(datetime.date(2026, 3, 21)), (1405, 1, 1))
        self.assertEqual(to_jalali(datetime.date(2024, 3, 20)), (1403, 1, 1))
        self.assertEqual(to_jalali("2026-03-21"), (1405, 1, 1))

    def test_formatting_is_localized(self):
        value = datetime.datetime(2026, 3, 21, 14, 30)
        persian = format_date(value, "fa", with_time=True)
        english = format_date(value, "en", with_time=True)
        self.assertIn("1405", persian)
        self.assertIn("فروردین", persian)
        self.assertIn("14:30", persian)
        self.assertEqual(english, "2026-03-21 14:30")
        self.assertIn("2026", format_date(value, "en"))

    def test_out_of_range_years_are_rejected(self):
        with self.assertRaises(ValueError):
            to_jalali(datetime.date(1700, 1, 1))

    def test_invalid_input_falls_back_to_text(self):
        self.assertEqual(format_date("not a date", "en"), "not a date")
        self.assertEqual(format_date(None, "en"), "—")


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.original = get_language()

    def tearDown(self):
        set_language(self.original)

    def test_switching_language_persists(self):
        self.assertEqual(set_language("fa"), "fa")
        self.assertEqual(get_language(), "fa")
        self.assertEqual(set_language("Persian"), "fa")
        self.assertEqual(set_language("en"), "en")
        self.assertEqual(get_language(), "en")

    def test_unsupported_language_is_rejected(self):
        with self.assertRaises(LanguageError):
            set_language("fr")

    def test_translation_falls_back_to_english_then_default(self):
        set_language("fa")
        self.assertEqual(t("features.enable_ok", label="حافظه"), "حافظه اکنون روشن است.")
        set_language("en")
        self.assertEqual(t("features.enable_ok", label="Memory"), "Memory is now ON.")
        self.assertEqual(t("missing.key", default="fallback"), "fallback")
        self.assertEqual(t("missing.key"), "missing.key")

    def test_rtl_wrap_adds_the_mark_only_for_persian(self):
        set_language("en")
        self.assertEqual(rtl_wrap("hello"), "hello")
        set_language("fa")
        wrapped = rtl_wrap("سلام")
        self.assertTrue(wrapped.startswith("\u200f"))
        self.assertEqual(rtl_wrap(wrapped), wrapped)

    def test_catalogs_have_identical_keys(self):
        catalogs = {}
        for code in LANGUAGES:
            path = Path(LOCALE_DIR) / f"{code}.json"
            catalogs[code] = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(catalogs["en"]), set(catalogs["fa"]))
        self.assertTrue(catalogs["fa"]["features.enable_ok"])

    def test_panel_chrome_follows_the_language(self):
        from reze.web.theme import panel_text, render_login, render_shell

        self.assertEqual(panel_text("Dashboard", "Dashboard", "en"), "Dashboard")
        self.assertEqual(panel_text("Dashboard", "Dashboard", "fa"), "داشبورد")
        set_language("fa")
        self.assertIn('lang="fa" dir="rtl"', render_login())
        set_language("en")
        self.assertIn('lang="en" dir="ltr"', render_shell("Dashboard", "body"))


if __name__ == "__main__":
    unittest.main()
