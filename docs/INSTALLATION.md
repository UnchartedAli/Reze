# Installation

REZE 3.0 runs as one Python process that serves both the Telegram userbot and
the web panel. This guide covers the guided installer, a manual setup, Docker,
systemd and managed platforms. Everything here assumes an account **you own**:
the session string is equivalent to your Telegram login.

## 1. Prerequisites

| Item | Why |
| --- | --- |
| Python 3.11+ | Runtime |
| Telegram `api_id` / `api_hash` | Created at https://my.telegram.org → API development tools |
| Your numeric Telegram user id | `REZE_OWNER_ID`; only this account can run commands |
| FFmpeg (optional) | Video/audio conversion and trimming |
| An AI API key (optional) | `.ai`, summaries, transcription, agent |
| `yt-dlp`, `gTTS` (optional) | Downloader commands and text-to-speech |

```bash
git clone <your-repository> reze
cd reze
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

FFmpeg is a system package, not a Python package:

- Windows: `winget install Gyan.FFmpeg`
- Debian/Ubuntu: `sudo apt install ffmpeg`
- macOS: `brew install ffmpeg`

If the binary is not on `PATH`, set `REZE_FFMPEG_PATH` to its full path.

## 2. Guided installer

```bash
python -m reze.installer
```

The installer is a standard-library terminal wizard with eight steps:

1. **System check** — Python version, required packages, FFmpeg, write access to
   the data directory.
2. **Telegram access** — API id/hash and owner id (validated).
3. **AI provider (optional)** — provider, model and key; can be skipped.
4. **Language** — English or Persian (`fa`).
5. **Storage and database** — data directory and SQLite URL.
6. **Companion (optional)** — bot token for the optional Bot Companion.
7. **Review** — masked summary of every value before writing.
8. **Database** — creates the data directory, opens the database and applies
   migrations up to schema v4.

Behaviour you can rely on:

- Every secret is masked while typing and in the review; secrets are never
  printed in clear text.
- Input is validated (numbers, language codes, URLs, data directory). Invalid
  input asks again instead of writing a broken file.
- An existing `.env` is never overwritten without confirmation. When you accept,
  the previous file is copied to `.env.bak-<timestamp>` first.
- The merge preserves your comments and ordering, updates known keys, appends
  unknown ones and is idempotent: running it twice with the same answers does
  not create a second backup.
- Ctrl+C exits cleanly without a traceback.
- The post-install menu lists **every optional feature as OFF** and lets you
  enable individual features. Nothing is enabled automatically.

Flags:

| Flag | Effect |
| --- | --- |
| `--check` | Run system checks only, write nothing |
| `--non-interactive` | Use defaults and existing values, no prompts |
| `--yes` | Accept overwrite prompts |
| `--no-menu` | Skip the post-install settings menu |
| `--env-file PATH` | Target environment file (default `.env`) |
| `--data-dir PATH` | Data directory (default `data`) |
| `--language en\|fa` | Interface language |

After `pip install .` the installer is also available as `reze-install`.

## 3. Manual setup

```bash
cp .env.example .env
# edit .env: REZE_API_ID, REZE_API_HASH, REZE_OWNER_ID,
#            REZE_PANEL_PASSWORD or REZE_PANEL_PASSWORD_HASH,
#            REZE_SECRET_KEY, REZE_VAULT_KEY
python scripts/generate_session.py
# paste the printed string into REZE_SESSION_STRING
python -m reze.app
```

Generate the two long random values once and store them safely:

```bash
python scripts/generate_hash.py                       # panel password hash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # REZE_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"   # REZE_VAULT_KEY
```

`REZE_VAULT_KEY` is the only key that can decrypt vault entries. Losing it means
losing that data; changing it makes existing entries unreadable. Keep it in a
password manager and out of the repository.

## 4. First start

`python -m reze.app` prints:

- the ASCII banner and version,
- the panel URL (default `http://127.0.0.1:8080`),
- the health endpoint,
- the database path and applied migration level.

Then:

1. Open the panel and sign in.
2. From any chat, send `.alive`, `.status` and `.diagnostics` to your own account.
3. Send `.features`. Everything is OFF. Enable one key at a time:
   `.features enable memory`, `.features enable vault confirm`.
4. Read `.help` and [COMMANDS.md](COMMANDS.md).

## 5. Docker

```bash
cp .env.example .env                  # fill in values
python scripts/generate_session.py    # run locally once
docker compose up -d --build
docker compose logs -f
```

`docker-compose.yml` mounts `./data` into the container. Back up that directory,
not just the database file. Do not bake `.env` into an image.

## 6. systemd (VPS)

```ini
[Unit]
Description=REZE 3.0
After=network-online.target

[Service]
Type=simple
User=reze
WorkingDirectory=/opt/reze
EnvironmentFile=/opt/reze/.env
ExecStart=/opt/reze/.venv/bin/python -m reze.app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now reze
journalctl -u reze -f
```

Keep the service user's home and the data directory readable only by that user
(`chmod 700`).

## 7. Managed platforms

- **Render / Railway / Koyeb / Fly.io** — set the `REZE_*` variables in the
  dashboard, use `REZE_SESSION_STRING` instead of a session file, and mount a
  persistent volume for `REZE_DATA_DIR`. Without a volume the SQLite database is
  lost on every deploy.
- **Reverse proxy** — terminate TLS at nginx/Caddy, set `REZE_PUBLIC_URL` to the
  public HTTPS URL, set `REZE_WEB_TRUST_PROXY=true` only when a trusted proxy
  sets the forwarded headers, and keep `REZE_WEB_HOST=127.0.0.1` so the panel is
  not directly reachable.

Platform notes and example files: [DEPLOY.md](../DEPLOY.md), `render.yaml`,
`railway.json`, `fly.toml`, `deploy/`.

## 8. Upgrading from 2.x

1. Stop the process.
2. Back up the database: stop Reze, then copy `data/reze.db` (and `data/` if you
   use the vault or Message Guard). A running-instance alternative is
   `.backup create` from Telegram.
3. Replace the code, keep `.env` and `data/`.
4. Start Reze. Migrations v3 and v4 run automatically, once, inside
   transactions and are recorded in `schema_migrations`.
5. Run `.features` — every optional key is OFF, including keys that did not exist
   before. Your 2.x settings (theme, prefix, AI model, guard rules) are preserved.

If a migration fails, the transaction rolls back and the process reports the
error. Restore the backup from step 2 before retrying with a newer build.

## 9. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No module named reze` | Activate the virtualenv and run from the repository root. |
| `REZE_API_ID / REZE_API_HASH are missing` | The client is disabled by design until both are set. |
| Panel refuses the default password | Set `REZE_PANEL_PASSWORD_HASH`; default login requires `REZE_ALLOW_INSECURE_DEFAULT_LOGIN=true`. |
| `database is locked` | Only one process may use a data directory. Stop the second instance. |
| Health endpoint returns `degraded` | Telegram is not connected or a service failed; check `/health` and `.diagnostics`. |
| Permission denied on `data/` | The service user must own the data directory. |
| FFmpeg not found | Install it or set `REZE_FFMPEG_PATH`. |

More: [CONFIGURATION.md](CONFIGURATION.md), [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md),
[README.fa.md](README.fa.md).
