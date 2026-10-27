"""
Configuration management for Reze Userbot.

Loads settings from environment variables with the ``REZE_`` prefix and provides
type-safe validation. The loader is deployment aware:

* On PaaS platforms (Render, Railway, Koyeb, Fly.io, Heroku, ...) the platform
  injected ``PORT`` variable becomes the web-panel port and the panel binds to
  ``0.0.0.0`` automatically.
* A writable data directory can be redirected with ``REZE_DATA_DIR`` so a
  persistent disk/volume can be mounted for the SQLite database and the
  Telethon session file.
* A Telethon ``StringSession`` can be supplied with ``REZE_SESSION_STRING`` so
  the userbot works on ephemeral filesystems without an interactive login.
"""

import os
from typing import List, Optional, get_origin

from pydantic import BaseModel, ConfigDict, Field

# Load a local .env when running directly on a VPS/laptop. On PaaS the platform
# injects environment variables and this is a no-op. The import is optional so
# the panel still starts even if python-dotenv is not installed.
try:
    from dotenv import load_dotenv

    # interpolate=False keeps password/hash/session values literal (a "$" in a
    # PBKDF2 hash or password must not be treated as a variable reference).
    try:
        load_dotenv(interpolate=False)
    except TypeError:  # older python-dotenv
        load_dotenv()
except ImportError:  # pragma: no cover - optional dependency
    pass


def _env(*names: str) -> Optional[str]:
    """Return the first non-empty environment variable from *names*."""
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return None


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _is_hosted_env() -> bool:
    """Best-effort detection of a managed hosting platform or container."""
    hosted_markers = (
        "PORT",
        "RENDER",
        "RENDER_EXTERNAL_URL",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_PROJECT_ID",
        "KOYEB_APP_NAME",
        "KOYEB_SERVICE_NAME",
        "FLY_APP_NAME",
        "DYNO",  # Heroku
    )
    if any(_env(name) for name in hosted_markers):
        return True
    # Inside a container the panel usually listens on 0.0.0.0; treat it as
    # hosted so the insecure admin/admin fallback cannot be exposed by mistake.
    return os.path.exists("/.dockerenv")


def detect_platform() -> str:
    """Human readable name of the platform Reze is running on."""
    if _env("RENDER", "RENDER_EXTERNAL_URL"):
        return "Render"
    if _env("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID"):
        return "Railway"
    if _env("KOYEB_APP_NAME", "KOYEB_SERVICE_NAME"):
        return "Koyeb"
    if _env("FLY_APP_NAME"):
        return "Fly.io"
    if _env("DYNO"):
        return "Heroku"
    if os.path.exists("/.dockerenv"):
        return "Docker"
    return "VPS / Local"


def _detect_public_url() -> Optional[str]:
    """Resolve the public URL of the panel from platform variables."""
    explicit = _env("REZE_PUBLIC_URL")
    if explicit:
        return explicit.rstrip("/")

    render_url = _env("RENDER_EXTERNAL_URL")
    if render_url:
        return render_url.rstrip("/")

    for var in ("RAILWAY_PUBLIC_DOMAIN", "KOYEB_PUBLIC_DOMAIN"):
        domain = _env(var)
        if domain:
            if domain.startswith(("http://", "https://")):
                return domain.rstrip("/")
            return f"https://{domain}".rstrip("/")

    fly_app = _env("FLY_APP_NAME")
    if fly_app:
        return f"https://{fly_app}.fly.dev"

    return None


class Settings(BaseModel):
    # ---------------------------------------------------------------- Telegram
    api_id: int = Field(default=0, alias="REZE_API_ID")
    api_hash: str = Field(default="", alias="REZE_API_HASH")
    phone: str = Field(default="", alias="REZE_PHONE")
    owner_id: int = Field(default=0, alias="REZE_OWNER_ID")
    session_path: str = Field(default="data/reze.session", alias="REZE_SESSION_PATH")
    session_string: str = Field(default="", alias="REZE_SESSION_STRING")
    proxy: str = Field(default="", alias="REZE_PROXY")

    # ------------------------------------------------------------------ Storage
    data_dir: str = Field(default="data", alias="REZE_DATA_DIR")
    database_url: str = Field(default="sqlite:///data/reze.db", alias="REZE_DATABASE_URL")

    # --------------------------------------------------------------- Web Panel
    web_host: str = Field(default="127.0.0.1", alias="REZE_WEB_HOST")
    web_port: int = Field(default=8080, alias="REZE_WEB_PORT")
    public_url: Optional[str] = Field(default=None, alias="REZE_PUBLIC_URL")
    panel_username: str = Field(default="admin", alias="REZE_PANEL_USERNAME")
    panel_password_hash: str = Field(default="", alias="REZE_PANEL_PASSWORD_HASH")
    panel_password: str = Field(default="", alias="REZE_PANEL_PASSWORD")
    secret_key: str = Field(
        default="reze-super-secret-key-change-me-in-production",
        alias="REZE_SECRET_KEY",
    )
    allowed_origins: List[str] = Field(
        default_factory=lambda: ["*"],
        alias="REZE_ALLOWED_ORIGINS",
    )
    allow_insecure_default_login: bool = Field(
        default=False,
        alias="REZE_ALLOW_INSECURE_DEFAULT_LOGIN",
    )

    # ------------------------------------------------- Behavior and timezone
    timezone: str = Field(default="Asia/Tehran", alias="REZE_TIMEZONE")
    log_level: str = Field(default="INFO", alias="REZE_LOG_LEVEL")
    clock_interval_minutes: int = Field(default=1, alias="REZE_CLOCK_INTERVAL_MINUTES")
    default_prefix: str = Field(default=".", alias="REZE_DEFAULT_PREFIX")

    # ------------------------------------------------------------- Safety limits
    max_purge_limit: int = Field(default=100, alias="REZE_MAX_PURGE_LIMIT")
    max_tagall_limit: int = Field(default=50, alias="REZE_MAX_TAGALL_LIMIT")

    model_config = ConfigDict(populate_by_name=True)

    # ---------------------------------------------------------------- Properties
    @property
    def has_panel_credentials(self) -> bool:
        """True when a panel password (plain or hashed) is configured."""
        return bool(self.panel_password_hash or self.panel_password)

    @property
    def session_backend(self) -> str:
        """``string`` when a StringSession is supplied, ``file`` otherwise."""
        return "string" if self.session_string else "file"

    @property
    def is_hosted(self) -> bool:
        """True when running on a managed PaaS platform."""
        return _is_hosted_env()

    @property
    def platform_name(self) -> str:
        return detect_platform()

    @property
    def effective_web_host(self) -> str:
        """Host the HTTP server should bind to."""
        return self.web_host or "0.0.0.0"

    @property
    def healthcheck_path(self) -> str:
        return "/healthz"

    @property
    def display_url(self) -> str:
        """Public URL if known, otherwise a browser-friendly local URL."""
        if self.public_url:
            return self.public_url
        host = self.effective_web_host
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        return f"http://{host}:{self.web_port}"

    @property
    def database_path(self) -> str:
        """Strip the SQLAlchemy-style prefix from ``database_url``."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return self.database_url[len(prefix):]
        return self.database_url

    @property
    def host_port(self) -> int:
        """Port advertised to the hosting platform."""
        return int(self.web_port)

    # ------------------------------------------------------------------ Loading
    @classmethod
    def load_from_env(cls) -> "Settings":
        """Load settings from environment variables with fallback defaults."""
        data = {}

        for field_name, field_info in cls.model_fields.items():
            env_var = field_info.alias or f"REZE_{field_name.upper()}"
            raw = os.getenv(env_var)
            if raw is None or raw.strip() == "":
                continue

            annotation = field_info.annotation
            if annotation is int:
                try:
                    data[field_name] = int(raw.strip())
                except ValueError:
                    continue
            elif annotation is bool:
                data[field_name] = _as_bool(raw)
            elif get_origin(annotation) is list:
                data[field_name] = [
                    item.strip() for item in raw.split(",") if item.strip()
                ]
            else:
                data[field_name] = raw.strip()

        # ------------------------------------------------------- Data directory
        data_dir = data.get("data_dir") or "data"
        data.setdefault("session_path", os.path.join(data_dir, "reze.session"))
        data.setdefault(
            "database_url",
            f"sqlite:///{os.path.join(data_dir, 'reze.db')}",
        )

        # ------------------------------------------------- PaaS port and binding
        # On Render/Railway/Koyeb the platform-assigned PORT is authoritative.
        platform_port = _env("PORT")
        if platform_port:
            try:
                data["web_port"] = int(platform_port)
            except ValueError:
                pass

        if "web_host" not in data:
            data["web_host"] = "0.0.0.0" if _is_hosted_env() else "127.0.0.1"

        if "public_url" not in data:
            detected_url = _detect_public_url()
            if detected_url:
                data["public_url"] = detected_url

        return cls(**data)

    # --------------------------------------------------------------- Validation
    def validate_production(self) -> List[str]:
        """Return a list of blocking configuration problems."""
        errors = []
        if not self.api_id:
            errors.append("REZE_API_ID is required and must be a valid integer.")
        if not self.api_hash:
            errors.append("REZE_API_HASH is required.")
        if not self.owner_id:
            errors.append("REZE_OWNER_ID is required to identify the bot owner.")
        if not self.has_panel_credentials:
            errors.append(
                "Set REZE_PANEL_PASSWORD (recommended for PaaS) or "
                "REZE_PANEL_PASSWORD_HASH (from scripts/generate_hash.py)."
            )
        return errors

    def deployment_notes(self) -> List[str]:
        """Non-fatal notes shown in the startup log and the web panel."""
        notes = []
        if not self.session_string and not os.path.exists(self.session_path):
            notes.append(
                "Telegram is not logged in yet: create a StringSession with "
                "scripts/generate_session.py and set REZE_SESSION_STRING, or "
                "run the bot once on a machine with a terminal."
            )
        if self.secret_key == "reze-super-secret-key-change-me-in-production":
            notes.append("REZE_SECRET_KEY is still the default value; change it in production.")
        if not self.has_panel_credentials:
            notes.append(
                "Panel password is not configured: web login is disabled until "
                "REZE_PANEL_PASSWORD or REZE_PANEL_PASSWORD_HASH is set."
            )
        return notes


# Global settings singleton
settings = Settings.load_from_env()
