# 🌸 Reze — Advanced Telegram Userbot & Web Control Panel

**Developed by [UnchartedAli](https://t.me/yamods) · Official channel: [@yamods](https://t.me/yamods)**

![Version](https://img.shields.io/badge/version-1.1.0-06b6d4)
![Python](https://img.shields.io/badge/python-3.11%2B-3b82f6)
![Telethon](https://img.shields.io/badge/engine-Telethon%20MTProto-10b981)
![License](https://img.shields.io/badge/license-MIT-9ca3af)

**Reze** is a modular, production-focused Telegram **userbot** built with Python 3.11+, Telethon MTProto, SQLite, and an integrated Persian **web control panel**. It runs on a VPS **and** on managed platforms such as **Render, Railway, Koyeb, Fly.io, Docker, and PaaS services with a `PORT` variable**.

---

## ✨ What's inside

- **⚡ Telethon MTProto engine** — 2FA, session persistence, automatic reconnect, FloodWait-safe operations.
- **🚀 PaaS-ready deployment** — binds to the platform `PORT` on `0.0.0.0`, exposes `/healthz`, handles `SIGTERM`, and ships with Docker, Render, Railway, and Fly configs plus a Koyeb guide.
- **🔑 Portable session** — `REZE_SESSION_STRING` (Telethon StringSession) works on ephemeral filesystems with no interactive terminal. A helper script generates/converts it.
- **🛡️ Group administration & protection** — `.ban`, `.kick`, `.mute`, `.purge`, `.pin`, `.tagall`, anti-flood, anti-raid, anti-link, blacklists, filters, warnings, notes.
- **⏰ Profile clock** — automatic name/bio clock with IANA timezones (`Asia/Tehran`, `UTC`, ...), configurable templates, and Telegram length limits.
- **🌐 Secure web panel** — dark RTL dashboard, PBKDF2-HMAC-SHA256 authentication, rate limiting, live logs, deployment diagnostics, and health endpoint.
- **🧩 Plugin system** — discover, load, unload, and inspect custom Python plugins at runtime.
- **🌍 Proxy support** — optional `REZE_PROXY=socks5://...` for networks where Telegram is filtered.

### 🆕 In v1.1.0

- Creator branding: **UnchartedAli** / **@yamods** across the package, panel, startup banner, and `.credits` command.
- Full deployment hardening for Render / Railway / Koyeb / Fly / Docker / VPS.
- `StringSession` support + `scripts/generate_session.py`.
- Public `/healthz` endpoint and Docker `HEALTHCHECK`.
- Graceful `SIGTERM` shutdown and MTProto reconnect with exponential backoff.
- Trust-proxy aware client IP handling and secure cookies behind HTTPS.
- Panel login is disabled until a password is configured (`REZE_ALLOW_INSECURE_DEFAULT_LOGIN` is for local development only).

---

## 🚀 Quick start (local / VPS)

```bash
git clone <YOUR_REPO_URL> reze && cd reze
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env          # fill REZE_API_ID, REZE_API_HASH, REZE_OWNER_ID, REZE_PANEL_PASSWORD

python -m reze.app
```

Reze loads `.env` automatically for local/VPS runs; PaaS platforms inject the variables directly.

The panel starts at `http://127.0.0.1:8080` (health: `http://127.0.0.1:8080/healthz`).
If the account is not logged in yet, run the bot once with a terminal and enter the phone/code, **or** generate a portable session:

```bash
python scripts/generate_session.py
```

> **Windows:** create the virtual environment with `py -m venv venv` and activate it with
> `.\venv\Scripts\Activate.ps1` before running the commands above.

---

## ☁️ Deploy anywhere

| Platform | How | Always-on? | Persistent data |
| :--- | :--- | :--- | :--- |
| **VPS (systemd)** | `deploy/reze.service` | ✅ | ✅ local `data/` |
| **Docker / Compose** | `docker compose up -d --build` | ✅ | ✅ `./data` volume |
| **Render** | `render.yaml` Blueprint / Docker | ⚠️ free sleeps | paid Disk |
| **Railway** | `railway.json` + Dockerfile | ✅ | Volume `/data` |
| **Koyeb** | Dockerfile, port `8080` | ⚠️ free scale-to-zero | Volume `/data` |
| **Fly.io** | `fly.toml` | ✅ | Volume `/data` |

**→ Full step-by-step guides (Persian): [`DEPLOY.md`](DEPLOY.md)**

### Render (summary)

1. Push to GitHub → Render **New → Blueprint** → select repo (`render.yaml` is auto-detected).
2. Set `REZE_API_ID`, `REZE_API_HASH`, `REZE_OWNER_ID`, `REZE_SESSION_STRING`, `REZE_PANEL_PASSWORD`.
3. Health check is already `/healthz`. Use a paid always-on instance for a 24/7 userbot.

### Railway / Koyeb (summary)

1. Deploy from GitHub; both detect the `Dockerfile`.
2. Add the same environment variables; set `REZE_WEB_HOST=0.0.0.0`.
3. Health check: `/healthz`. For persistence mount a volume at `/data` and set `REZE_DATA_DIR=/data`.
4. Run **one** instance only.

> ⚠️ **Never set `REZE_WEB_PORT` on a PaaS that injects `PORT`** (Render/Railway/Koyeb). Reze picks `PORT` automatically. Setting it manually can break the platform's routing.

---

## 🔐 Sessions & persistence

| Mode | Variable | Use case |
| :--- | :--- | :--- |
| String session | `REZE_SESSION_STRING` | Render / Railway / Koyeb / any ephemeral filesystem |
| File session | `REZE_SESSION_PATH` | VPS / Docker with a persistent volume |

Generate a string session locally:

```bash
python scripts/generate_session.py
# or convert an existing file:
python scripts/generate_session.py --from-file data/reze.session --api-id ... --api-hash ...
```

The app also keeps a copy of the active string session at `<data_dir>/session_string.txt` when using the string backend, so it can be recovered from a mounted volume.

**SQLite data** (filters, settings, warnings, notes) lives in `<data_dir>/reze.db`. Mount `/app/data` (Render), `/data` (Railway/Koyeb/Fly), or `./data` (Compose) to keep it across restarts.

---

## ⚙️ Configuration

All configuration is environment-based. See [`.env.example`](.env.example) for every option and [`DEPLOY.md`](DEPLOY.md) for the full table.

Minimum for a working hosted userbot:

```env
REZE_API_ID=12345678
REZE_API_HASH=abcdef...
REZE_OWNER_ID=123456789
REZE_SESSION_STRING=1BVtsOK4...
REZE_PANEL_PASSWORD=a-strong-password
REZE_WEB_HOST=0.0.0.0
```

Optional highlights:

- `REZE_PUBLIC_URL` — public panel URL (auto-detected on Render/Railway/Koyeb).
- `REZE_PROXY` — SOCKS5/HTTP MTProto proxy.
- `REZE_DATA_DIR` — persistent volume path.
- `REZE_TIMEZONE` — default `Asia/Tehran`.
- `REZE_ALLOW_INSECURE_DEFAULT_LOGIN` — local development only, never on a public deployment.

---

## 🌐 Web control panel

- `/` — dashboard, live stats, Telegram connection status, deployment diagnostics.
- `/profile` — name/bio clock settings.
- `/groups`, `/security`, `/filters` — group management and automation.
- `/logs` — live in-memory logs (credentials are masked).
- `/settings` — platform, session backend, storage, and environment checklist.
- `/healthz` — public health endpoint for PaaS health checks (no auth).

The panel shows the creator and official channel in the header, sidebar, and footer.

---

## 🤖 Commands

| Category | Commands |
| :--- | :--- |
| General | `.help`, `.ping`, `.alive`, `.credits`, `.info`, `.id`, `.stats`, `.uptime`, `.version`, `.settings`, `.logs`, `.webpanel`, `.shutdown`, `.restart` |
| Profile | `.setname`, `.setbio`, `.nameclock`, `.bioclock`, `.clockformat`, `.timezone`, `.clockstatus`, `.clockpreview`, `.setprefix` |
| Admin | `.ban`, `.unban`, `.kick`, `.mute`, `.unmute`, `.purge`, `.del`, `.pin`, `.unpin`, `.admins`, `.tagall`, `.slowmode` |
| Moderation | `.warn`, `.warnings`, `.resetwarns`, `.rules`, `.welcome`, `.goodbye`, `.filter`, `.blacklist`, `.note` |
| Security | `.antiflood`, `.antiraid`, `.antilink`, `.lock`, `.unlock` |
| Privacy | `.privacy`, `.sessions`, `.backup` |
| Plugins | `.plugins`, `.plugin` |

`.credits` (aliases: `creator`, `developer`, `support`) prints the author and channel.

---

## 📂 Project structure

```
reze/
├── app.py                  # Bootstrap: panel + MTProto + scheduler, graceful shutdown
├── config.py               # Env configuration, PaaS/platform detection
├── telegram_client.py      # Telethon client, StringSession, proxy, reconnect
├── database.py             # SQLite WAL persistence (data dir aware)
├── scheduler.py            # Name/Bio clock with FloodWait backoff
├── command_router.py       # Dot-command parser and dispatcher
├── plugin_manager.py       # Dynamic plugin loader
├── commands/               # Modular command suites
├── modules/                # AntiFlood, AntiRaid, filters, greetings, notes
├── web/
│   ├── app.py              # HTTP panel, health endpoint, RTL UI
│   └── auth.py             # PBKDF2 hashing, sessions, rate limiting
└── plugins/                # Custom user plugins

Dockerfile                  # Production image (drops to non-root, volume-aware)
docker-compose.yml          # VPS deployment
render.yaml                 # Render Blueprint
railway.json                # Railway config
fly.toml                    # Fly.io config
deploy/                     # systemd, nginx, container entrypoint
scripts/                    # generate_session.py, generate_hash.py, healthcheck.py
DEPLOY.md                   # Full Persian deployment guide
```

---

## 🛡️ Security notes

- Use a strong `REZE_PANEL_PASSWORD` (or `REZE_PANEL_PASSWORD_HASH`).
- Never commit `.env`, `data/`, session files, or `session_string.txt`.
- Run one instance per Telegram session.
- Keep the panel behind HTTPS when exposed publicly.
- Revoke a leaked session from Telegram → Settings → Devices immediately.

---

## 🧪 Tests

```bash
python -m unittest discover -s tests -v
```

---

## 💚 Credits

**Reze** is developed and maintained by **[UnchartedAli](https://t.me/yamods)**.
Official Telegram channel: **[@yamods](https://t.me/yamods)**.

If Reze is useful to you, join the channel and share the project.

---

## 📜 License

Released under the **MIT License** — see [LICENSE](LICENSE).
