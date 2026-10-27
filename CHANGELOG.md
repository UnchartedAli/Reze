# Changelog

All notable changes to **Reze** are documented here.
Developer: **UnchartedAli** · Channel: **[@yamods](https://t.me/yamods)**

## [1.1.0] — 2026-10-27

### Added
- Creator branding across the package, startup banner, web panel, README, license, and deployment files.
- `.credits` command (aliases: `creator`, `developer`, `support`).
- Portable Telethon `StringSession` support via `REZE_SESSION_STRING` (PaaS-friendly).
- `scripts/generate_session.py` to create or convert a session string.
- Public `/healthz` endpoint for Render/Railway/Koyeb/Fly health checks (GET and HEAD).
- Docker support: `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`, `HEALTHCHECK`.
- Deployment configs: `render.yaml`, `railway.json`, `fly.toml`, `docker-compose.yml`, `Procfile`.
- Full Persian deployment guide (`DEPLOY.md`) for Render/Railway/Koyeb/Fly/Docker/VPS.
- Optional SOCKS5/HTTP proxy support via `REZE_PROXY`.
- Optional persistent-volume support via `REZE_DATA_DIR`.
- Graceful `SIGTERM` shutdown and MTProto reconnect with exponential backoff.
- One-time interactive phone/code login on VPS/local terminals.
- Trust-proxy aware client IP detection and secure cookies behind HTTPS.
- Automatic `.env` loading for local/VPS runs (`python-dotenv`).

### Changed
- The web panel now binds to `0.0.0.0` on PaaS and uses the platform `PORT` automatically.
- The database path derives from `REZE_DATA_DIR`; fallback to a temporary DB if the volume is unwritable.
- Panel login is disabled until `REZE_PANEL_PASSWORD` or `REZE_PANEL_PASSWORD_HASH` is set.
- The HTTP server is threaded, so health checks stay responsive.
- Log HTML is escaped; security headers added.

### Security
- Removed the insecure default admin/admin login unless `REZE_ALLOW_INSECURE_DEFAULT_LOGIN=true` is explicitly set.
- Session snapshot files are written with `0600` permissions and ignored by git.
- Sensitive log masking no longer mangles ports/paths.

## [1.0.0]
- Initial public Reze release.
