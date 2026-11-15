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

## 5-check. Verify the image before you deploy

`scripts/docker_e2e.sh` builds the image and runs it the way a managed host does. It sets `PORT`,
mounts a named volume, and checks health. It then runs the page smoke test, restarts the container, and
confirms that no migration runs again:

```bash
bash scripts/docker_e2e.sh 3000    # PASS when every step succeeds
```

What was verified in this way (see the roadmap for the exact record):

* The image builds from the repository's `Dockerfile` and starts.
* With `PORT=3000` the app listens on 3000. With `PORT` unset, compose publishes 8080.
* `/healthz` returns 200, and Docker reports the container healthy.
* The app process runs as the unprivileged `reze` user, not root.
* The named volume keeps data across a restart, and no migration runs again after restart.
* All 15 navigation pages load for a signed-in owner.

Caveat: the test environment could not reach Docker Hub, so the build used a local Ubuntu 24.04
base with the same Python 3.12 in place of `python:3.12-slim`. The Dockerfile itself was not changed.
A real build with Docker Hub access is still worth running once.

## 5a. Cloady

Cloady (cloady.com) runs REZE from this repository. It builds the `Dockerfile`
and runs one container with public HTTPS and a persistent volume. The same
`docker-compose.yml` also works on a VPS.

Public Cloady documentation shows three ways to deploy: the Cloady CLI
(`cloady deploy ./folder`, or `cloady deploy --type=git <repo-url> --subdir <dir>`),
the dashboard, and an MCP server for AI assistants at `https://cloady.com/api/mcp`
(OAuth). This guide uses the CLI or dashboard. Full reference: https://cloady.com/docs.

### 1. Check the files before deploying

```bash
python -m reze.deploy.compose_check docker-compose.yml
```

The checker reads the compose file offline. It exits 1 on any error and reports
each finding with its source. A passing run looks like `result: PASS (0 error(s)...)`.
It catches the common Cloady failures:

- a host bind mount (`./data:/app/data`) instead of a declared named volume
- a fixed host port instead of `${PORT:-8080}`
- a secret written into the compose file
- more than one replica (two instances would share one Telegram session)
- `.env` committed without a `.gitignore` entry

Install PyYAML first if needed: `pip install -r requirements-dev.txt`.

### 2. Set the secrets in Cloady

Enter these in the Cloady dashboard as secrets (or in the CLI). They are never
placed in the repository. The compose file reads them through `env_file: .env`.

```dotenv
REZE_API_ID=123456
REZE_API_HASH=...
REZE_OWNER_ID=123456789
REZE_SESSION_STRING=...
REZE_PANEL_USERNAME=admin
REZE_PANEL_PASSWORD_HASH=...
REZE_SECRET_KEY=...
REZE_PUBLIC_URL=https://<your-cloady-address>
REZE_WEB_TRUST_PROXY=true
REZE_TIMEZONE=UTC
```

Generate the values as described in section 1 of this guide. Use the hash, not
`REZE_PANEL_PASSWORD`. The hash contains `$`, so if you ever write it into a
compose file, escape each `$` as `$$`.

### 3. Deploy

Run `cloady deploy ./` from the repository, or create the app in the Cloady
dashboard from the GitHub repository. Cloady will show which build path it uses.
The repository has both a `Dockerfile` and a compose file, so confirm this in the
dashboard. Public samples show the two paths separately.

### 4. Verify

1. Open `https://<your-cloady-address>/healthz`. It should return `{"status":"ok"}`.
2. Log in to the panel with the username and the password that matches the hash.
3. Send `.id` from your Telegram account to confirm the userbot is online.

### Cloady behaviour to confirm on the first deploy

These points are not confirmed by Cloady's public documentation, so the checker
reports them as heuristics, and you should check them yourself:

- **Port.** Cloady starts apps on `PORT`. The compose file publishes
  `${PORT:-8080}`, and Reze listens on `PORT` at runtime. If Cloady does not
  resolve `${PORT}` when it reads the compose file, the published port will still be
  8080 while the app listens on another port. The symptom is a failed health check.
  In that case, set `ports:` to match the value Cloady reports.
- **Disk size.** The volume has no `driver_opts.size`, so Cloady applies its default
  size. Set a size in the dashboard if you need one. Docker's local driver does
  not accept that option, so it is not in the compose file.
- **Build path.** If Cloady builds from the Dockerfile and ignores the compose file,
  the compose-level settings (volume, environment) must be set in the dashboard
  instead.

Cloady notes:

- Run **one** instance. The same Telegram session must not connect twice.
- `REZE_WEB_TRUST_PROXY=true` belongs only where a proxy terminates HTTPS, as it
  does on Cloady. On a VPS that exposes port 8080 directly, keep it off, because
  it would let clients spoof `X-Forwarded-For`. See `docs/SECURITY.md`.
- `.dockerignore` keeps `.env`, `*.session`, and the local `data/` folder out of the image.

### Sticker bot and Watchdog on Cloady

Two more secrets, and both are stored encrypted by Reze once imported:

* `REZE_VAULT_KEY`: required for any stored secret. Keep it; without it nothing stored can be opened.
* `REZE_STICKER_BOT_TOKEN`: the @watchdogappbot token. Import once, then remove it from the Cloady panel.
* `REZE_WATCHDOG_BRIDGE_SECRET`: the same value as the worker's `REZE_BRIDGE_SECRET`. Import once, then remove it.
* `REZE_WATCHDOG_URL`: defaults to `https://amo.alimmazza043.workers.dev`.

On the Watchdog worker, set `REZE_HEALTH_URL` to this app's public `/healthz` address. The cron then tells
you if Cloady stops answering. See `integrations/watchdog/README.md`.

### Moving an existing VPS install from `./data` to the named volume

Older copies of `docker-compose.yml` stored data in `./data`. Copy it into the
named volume once:

```bash
docker compose up --no-start                       # creates the volume
VOL=$(docker volume ls -q | grep reze_data)         # e.g. reze_reze_data
docker run --rm -v "$PWD/data:/from" -v "$VOL:/to" alpine sh -c 'cp -a /from/. /to/'
docker compose up -d
```

Keep the `./data` folder as a backup until the bot is running correctly.

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
