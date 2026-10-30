# Localization (English / Persian)

REZE 3.0 is bilingual at the interface level. English is the source language;
Persian is a first-class catalog, not a machine translation layer.

## What is translated

| Surface | English | Persian |
| --- | --- | --- |
| Command names, aliases, syntax | Yes | Yes — identical names and syntax |
| Reply framing, status words, labels | Yes | Yes |
| Help index, category names, feature names | Yes | Yes |
| Web panel navigation, login screen, direction | Yes | Yes |
| Web panel page bodies | Yes | English in 3.0 |
| Error and validation messages | Yes | Yes |
| Free-text input, notes, search | Yes | Yes, with normalization |
| Dates | ISO/Gregorian | Optional Jalali rendering |
| Per-command one-line descriptions | Yes | English fallback in 3.0 |
| Documentation | Yes | [README.fa.md](README.fa.md) |

## Switching language

```text
.language           show the current language
.language fa        switch to Persian
.language en        switch back
```

or in the panel: **Settings → Language**. The choice is stored as the
`language` preference in SQLite, so it survives restarts and migrations. The
`REZE_LANGUAGE` environment variable is the initial default.

## Catalogs

- Files: `reze/localization/locales/en.json` and `fa.json`.
- 124 keys, with parity between the two catalogs (enforced by a test).
- Lookup: `t("key", "English fallback")`; the English fallback is used when a
  key is missing or the catalog cannot be read. A missing key never raises.
- Formatting uses `str.format` values, for example
  `t("help.category_line", "{name}: {count} commands", name=..., count=...)`.
- Packages include the catalogs through
  `[tool.setuptools.package-data] "reze.localization" = ["locales/*.json"]`.

## Right-to-left layout

- `is_rtl()` reports whether the active language is right-to-left.
- `rtl_wrap(text)` prefixes replies with U+200F (RIGHT-TO-LEFT MARK) when the
  language is Persian, so Telegram aligns framed panels correctly.
- The panel sets `dir="rtl"` for Persian and keeps the terminal theme.
- Stored text is normalized without bidi control characters; direction is
  applied at render time, not persisted.

## Persian normalization

`reze/localization/normalize.py` normalizes before storing or comparing:

| Rule | Example |
| --- | --- |
| Arabic YEH / ALEF MAKSURA → FARSI YEH | `ي`, `ى` → `ی` |
| ARABIC KAF → KEHEH | `ك` → `ک` |
| TEH MARBUTA → HEH | `ة` → `ه` |
| Remove tatweel and harakat | `مـی‌رود` → `میرود` |
| Persian and Arabic-Indic digits → ASCII | `۱۲۳`, `١٢٣` → `123` |
| Remove LRM/RLM and bidi embeddings | invisible controls stripped |
| Collapse horizontal whitespace | multiple spaces → one |
| Keep ZWNJ | `می‌رود` stays one word with its ZWNJ |

Consequences:

- `.find`, `.search`, `.usearch` and `.memory search` match regardless of which
  Arabic/Persian letter variant was typed.
- Amounts and dates typed with Persian digits are parsed as numbers.
- Text that merely contains Persian letters is detected by `has_persian()`; that
  is used for alerts and classification, not for switching the UI language.

## Dates

- Storage is always ISO-8601 UTC. Nothing is stored in Jalali.
- `format_date(value, language="fa", with_time=False)` renders the Jalali
  calendar using the arithmetic conversion in `reze/localization/jalali.py`.
- Known conversions are covered by tests, including 2026-03-21 → 1405-01-01 and
  2024-03-20 → 1403-01-01.
- Out-of-range dates raise a clear error instead of returning a wrong date.
- Reminders and schedules are evaluated in `REZE_TIMEZONE`.

## Adding a language

1. Copy `locales/en.json` to `locales/<code>.json` and translate the values;
   keep the keys.
2. Add the code to `LANGUAGES` in `reze/localization/manager.py`.
3. If the language is right-to-left, add it to `is_rtl()`.
4. Run the localization tests; catalog parity is checked per file.

Command names are not localized per language: the same `.memory` works in both
modes. Translating command names would break muscle memory and documentation.

## Known limits

- Command one-line descriptions in `.help` remain English in 3.0.
- Persian text in generated AI answers depends on the configured model.
- Jalali conversion covers the supported date range; it is arithmetic, not a
  full historical calendar library.
- The ASCII frame is designed for monospace fonts; Persian glyph shaping is done
  by Telegram, not by REZE.
