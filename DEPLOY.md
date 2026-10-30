# Deployment guide

REZE 3.0 runs as a single Python process that serves both the Telegram userbot
and the web panel. This guide covers a VPS, Docker, and managed platforms
(Render, Railway, Koyeb, Fly.io).

> Operate Reze only on an account you own. The session string is equivalent to
> your Telegram login.

## 1. Prepare once

1. Create a Telegram application at https://my.telegram.org and note the
   `api_id` and `api_hash`.
2. Find your numeric account id (send `.id` after setup, or use any client).
3. Generate a portable session:

   ```bash
   pip install -r requirements.txt
   python scripts/generate_session.py
   ```

   Store the printed string as `REZE_SESSION_STRING`. Never commit it.
4. Create a panel password hash:

   ```bash
   python scripts/generate_hash.py
   ```

5. Pick a long random `REZE_SECRET_KEY`:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

## 2. Environment

Copy `.env.example` to `.env` and fill in at least:

```dotenv
REZE_API_ID=123456
REZE_API_HASH=...
REZE_OWNER_ID=123456789
REZE_SESSION_STRING=...
REZE_PANEL_PASSWORD_HASH=...
REZE_SECRET_KEY=...
REZE_WEB_HOST=127.0.0.1
REZE_WEB_PORT=8080
REZE_DATA_DIR=/var/lib/reze
```

Optional: `REZE_AI_*` for AI commands, `REZE_FFMPEG_PATH` when FFmpeg is not on
`PATH`, `REZE_REMOVEBG_API_KEY` for background removal,
`REZE_ALLOWED_ORIGINS` only if you build a separate frontend.

## 3. VPS with systemd

```ini
# /etc/systemd/system/reze.service
[Unit]
Description=Reze Telegram userbot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=reze
WorkingDirectory=/opt/reze
EnvironmentFile=/opt/reze/.env
ExecStart=/opt/reze/.venv/bin/python -m reze.app
Restart=always
RestartSec=5
# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/lib/reze
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd -r -s /usr/sbin/nologin reze
sudo mkdir -p /var/lib/reze && sudo chown reze:reze /var/lib/reze
sudo systemctl daemon-reload
sudo systemctl enable --now reze
sudo journalctl -u reze -f
```

`ProtectHome=true` requires the app directory to live outside `/home`; adapt the
unit if you keep it in a home directory.

## 4. Docker

The repository ships a `Dockerfile` and `docker-compose.yml` as a starting point
(they are not published images). Install FFmpeg in the image if you need video
commands:

```bash
docker build -t reze:3.0.0 .
docker run -d --name reze --env-file .env \
  -v reze-data:/app/data -p 127.0.0.1:8080:8080 reze:3.0.0
```

Behind a reverse proxy, set `REZE_WEB_TRUST_PROXY=true` so cookies become
`Secure` and client addresses are read from `X-Forwarded-*`.

## 5. Managed platforms (Render, Railway, Koyeb, Fly.io)

- The platform `PORT` variable overrides `REZE_WEB_PORT` and the panel binds to
  `0.0.0.0` when a hosted environment is detected.
- Set all secrets as platform environment variables, not files.
- Use `REZE_SESSION_STRING` — ephemeral filesystems lose session files.
- Mount a persistent volume for `REZE_DATA_DIR` if you want the SQLite database
  (archive, reminders, automations, settings) to survive deployments.
- Health check path: `/healthz` (returns `{"status":"ok"}`).
- The panel password is mandatory in hosted mode; login stays disabled without
  `REZE_PANEL_PASSWORD` or `REZE_PANEL_PASSWORD_HASH`.

## 6. Reverse proxy (nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name reze.example.com;

    ssl_certificate     /etc/letsencrypt/live/reze.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/reze.example.com/privkey.pem;

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then set `REZE_PUBLIC_URL=https://reze.example.com` and
`REZE_WEB_TRUST_PROXY=true`. Without a proxy, leave the panel on `127.0.0.1`
and reach it through an SSH tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 user@server
```

## 7. Operations

| Task | Command |
| --- | --- |
| Health | `curl -fsS http://127.0.0.1:8080/healthz` |
| Logs (systemd) | `journalctl -u reze -f` |
| Logs (Telegram) | `.logs 20` |
| Diagnostics | `.diagnostics` |
| Backup | `.backup` (timestamped copy in the data dir) |
| Stop cleanly | `.shutdown` or `systemctl stop reze` |

Backups: stop the service (or use SQLite's WAL-safe copy) and archive
`REZE_DATA_DIR`. The database holds no Telegram credentials, but it does hold
your notes, archive and automation rules.

## 8. Security checklist

- [ ] Panel on loopback or behind TLS with `REZE_WEB_TRUST_PROXY=true`.
- [ ] Strong panel password hash, not the plaintext variable.
- [ ] Unique `REZE_SECRET_KEY`.
- [ ] `.env` and session files excluded from version control and backups you
      share.
- [ ] Dedicated Telegram account where possible.
- [ ] Review installed plugins; they are not sandboxed.
- [ ] Keep dependencies updated (`pip install -U -r requirements.txt`).

## 9. Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Panel loads, bot offline | `REZE_SESSION_STRING` missing/expired, or api id/hash absent |
| `AuthKeyUnregisteredError` | session revoked — generate a new one |
| `401` after restart on PaaS | ephemeral filesystem; use a StringSession |
| Login page says disabled | no `REZE_PANEL_PASSWORD(_HASH)` configured |
| `FloodWait` on many operations | Telegram rate limit; wait or lower concurrency |
| Media commands fail with "Pillow is required" | `pip install Pillow` |
| Video commands fail with "FFmpeg is not installed" | install FFmpeg or set `REZE_FFMPEG_PATH` |
| `.stickerpack` rejects the image | unsupported format or an image the sticker pipeline cannot normalise |
| AI commands say "not configured" | provider/model/key missing |
