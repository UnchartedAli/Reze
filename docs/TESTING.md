# Testing and development

## 1. Running the suite

```bash
python -m unittest discover -s tests -v
```

Requirements: Python 3.11+, `pip install -r requirements.txt`. No Telegram
credentials, network access or paid AI keys are needed. Tests that need Pillow
are skipped automatically when it is not installed; FFmpeg tests never invoke
the real binary.

Useful subsets:

```bash
python -m unittest discover -s tests -p "test_core.py" -v
python -m unittest discover -s tests -p "test_web.py" -v
python -m unittest tests.test_productivity_automation -v
```

## 2. How the suite isolates itself

`tests/support.py` points `REZE_DATA_DIR` and `REZE_DATABASE_URL` at a temporary
directory **before** any `reze` module is imported, so the global configuration
singleton never touches your real database or session. It also provides:

- `DummyMessage` / `DummyClient` — Telethon-like doubles for commands, media
  downloads and MTProto request capture;
- `make_context()` — builds a real `CommandContext`;
- `run()` — runs a coroutine in a fresh event loop.

## 3. What is covered

| Area | Tests |
| --- | --- |
| Configuration | defaults, PaaS port binding, data-dir derivation, AI/vision flags |
| Storage | schema, group settings, warnings, filters, blacklists, key/value settings, archive, notes, reminders, plugin state, bounded task log |
| Auth | PBKDF2 hashing, session TTL, CSRF validation |
| Router | registration, aliases, duplicate rejection, dispatch, owner gating, cooldowns, long-message splitting, error reporting |
| ASCII engine | themes, rectangular frames, escaping, splitting with code-span balancing, preview |
| Tasks | completion, failure, timeout, cancellation (running and queued), queue limit |
| Confirmations | single use, action/chat/user binding, expiry |
| Presence | preference roundtrip, no-op when disabled, real `UpdateStatusRequest` when enabled, FloodWait cooldown, error capture, command on/off/status, owner-only metadata |
| Plugins | manifest validation, duplicate commands, manifest mismatch rollback, failure isolation, enable/disable persistence, typed settings |
| Media | probe/resize/compress/caption/meme/thumbnail, 512×512 WebP sticker, workspace traversal guards, FFmpeg argument arrays and missing dependency |
| Sticker sets | request construction (`CreateStickerSet`, `AddStickerToSet`), short-name rules, asset validation |
| AI | request shape per provider, parsing, error mapping, retries, fallback disclosure, vision gating, prompt limits |
| Web panel | real HTTP: health, redirect, login, CSRF rejection/acceptance, escaping, headers, API auth, logout |
| QR | BCH format/version words, Reed-Solomon vectors from the spec, matrix geometry, PNG output |
| Automation | validation, CRUD, keyword execution, cooldown, outbound authorization, allowlist, recursion guard |
| End-to-end command flows | `.sticker` (download → convert → upload), `.stickerpack` confirmation → real request, `.help`, `.aiinfo` |

## 4. What is *not* covered

- Real Telegram API calls: no live sticker-set creation, message sending or
  login is exercised. Sticker requests are asserted through a fake client.
- Live AI provider calls: transports are replaced by deterministic fakes.
- FFmpeg conversions: the binary is absent in the reference environment, so
  only argument construction, validation and error handling are tested.
- Browser-level UI tests: the panel is exercised over HTTP, not with a headless
  browser (no JavaScript is used).
- Load, soak and concurrency stress tests.

## 5. Linting and type checks

The project ships a `[tool.ruff]` configuration. In the reference environment
(offline, no package index) `ruff` could not be installed, so linting was not
executed; run it yourself with:

```bash
pip install ruff
ruff check .
```

No type checker is configured. Adding `mypy` or `pyright` is a good next step;
the code is annotated but not strictly typed.

## 6. Development workflow

1. `git switch -c feature/<name>`
2. Implement in small slices; keep the ASCII renderer and task manager as the
   shared infrastructure.
3. Add tests next to the behaviour you changed.
4. Run the full suite before committing.
5. Update `CHANGELOG.md` and the relevant `docs/` page.

Debugging tips:

- `REZE_LOG_LEVEL=DEBUG` raises verbosity; the panel `/logs` shows the buffer.
- `.diagnostics` reports integration readiness.
- The panel `/api/status` returns a compact JSON snapshot for scripts.
- Session problems: regenerate with `python scripts/generate_session.py`.
