"""
Plugin manifest model and validation.

A manifest is a *consent and accountability* document: it tells Reze and the
user what a plugin is, which commands it adds, what it depends on and which
capabilities it wants. It is deliberately **not** a sandbox — third-party
plugins run in the same Python process as the userbot and can bypass any
declared permission. See docs/PLUGIN_GUIDE.md for the full policy.
"""

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from reze import __version__
from reze.exceptions import ManifestError

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}){0,3}$")

#: Capabilities a plugin may request. ``config.secrets`` is never granted to
#: external plugins and is reported as a hard warning if requested.
CAPABILITIES: Dict[str, str] = {
    "telegram.message": "Send and edit Telegram messages",
    "telegram.media": "Read media attached to replied-to messages",
    "telegram.account": "Read account and chat metadata",
    "filesystem.read": "Read files inside the Reze data directory",
    "filesystem.write": "Write files inside the Reze data directory",
    "network": "Make outbound network requests",
    "ai.provider": "Send content to the configured AI provider",
    "process.exec": "Start local processes such as FFmpeg",
    "config.read": "Read non-secret configuration",
    "config.secrets": "Read secrets (never granted to third-party plugins)",
}

FIELD_TYPES = {"string", "int", "bool", "choice", "secret"}


def parse_version(value: str) -> tuple:
    return tuple(int(part) for part in re.findall(r"\d+", value or "0")[:3]) or (0,)


def is_compatible(minimum: str) -> bool:
    """True when the running Reze satisfies the plugin's minimum version."""
    current = parse_version(__version__)
    required = parse_version(minimum)
    length = max(len(current), len(required))
    return current + (0,) * (length - len(current)) >= required + (0,) * (length - len(required))


class PluginManifest(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    id: str = ""
    version: str = "1.0.0"
    description: str = Field(..., min_length=3, max_length=400)
    author: str = ""
    source: str = ""
    category: str = "Plugins"
    tags: List[str] = Field(default_factory=list)
    commands: List[str] = Field(default_factory=list)
    requires: List[str] = Field(default_factory=list)
    optional_requires: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    min_reze_version: str = "2.0.0"
    config: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if value and not ID_RE.match(value):
            raise ValueError("id must be 2-32 characters: lowercase letters, digits, '-' or '_'")
        return value

    @field_validator("version", "min_reze_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if not VERSION_RE.match(value or ""):
            raise ValueError("version must look like 1.0.0")
        return value

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, values: List[str]) -> List[str]:
        unknown = [value for value in values if value not in CAPABILITIES]
        if unknown:
            raise ValueError(
                "unknown capability: " + ", ".join(unknown)
                + " (valid: " + ", ".join(sorted(CAPABILITIES)) + ")"
            )
        return list(dict.fromkeys(values))

    @field_validator("commands")
    @classmethod
    def _validate_commands(cls, values: List[str]) -> List[str]:
        for value in values:
            if not re.match(r"^[a-z0-9_]{1,32}$", value or ""):
                raise ValueError(f"invalid command name '{value}'")
        return list(dict.fromkeys(values))

    @field_validator("config")
    @classmethod
    def _validate_config(cls, values: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        for key, spec in values.items():
            if not re.match(r"^[a-z0-9_]{1,32}$", key or ""):
                raise ValueError(f"invalid configuration key '{key}'")
            if not isinstance(spec, dict):
                raise ValueError(f"configuration '{key}' must be an object")
            kind = spec.get("type", "string")
            if kind not in FIELD_TYPES:
                raise ValueError(
                    f"configuration '{key}' has unsupported type '{kind}' "
                    f"(valid: {', '.join(sorted(FIELD_TYPES))})"
                )
            if kind == "choice" and not spec.get("choices"):
                raise ValueError(f"configuration '{key}' of type choice needs 'choices'")
        return values

    # ------------------------------------------------------------------ helpers
    @property
    def warnings(self) -> List[str]:
        notes = []
        if not self.author:
            notes.append("No author declared.")
        if not self.source:
            notes.append("No source declared; the plugin cannot be audited by origin.")
        if "config.secrets" in self.permissions:
            notes.append("Requests access to secrets; never granted to third-party plugins.")
        if "process.exec" in self.permissions:
            notes.append("Wants to start local processes.")
        return notes

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        data["warnings"] = self.warnings
        return data


def build_manifest(data: Any, fallback_id: str = "") -> PluginManifest:
    """Validate raw manifest data (dict or model) into a manifest object."""
    if isinstance(data, PluginManifest):
        manifest = data
    elif isinstance(data, dict):
        payload = dict(data)
        payload.setdefault("id", fallback_id)
        try:
            manifest = PluginManifest(**payload)
        except ValidationError as exc:
            problems = []
            for error in exc.errors()[:3]:
                location = ".".join(str(part) for part in error["loc"]) or "manifest"
                problems.append(f"{location}: {error['msg']}")
            raise ManifestError("Invalid plugin manifest - " + "; ".join(problems)) from exc
    else:
        raise ManifestError("The plugin must export a MANIFEST dictionary.")

    if not manifest.id:
        manifest.id = fallback_id or re.sub(r"[^a-z0-9_-]", "-", manifest.name.lower())[:32]
    if not ID_RE.match(manifest.id):
        raise ManifestError(f"Invalid plugin id '{manifest.id}'.")
    if not is_compatible(manifest.min_reze_version):
        raise ManifestError(
            f"Plugin requires Reze >= {manifest.min_reze_version}; this build is {__version__}."
        )
    return manifest


def example_manifest() -> PluginManifest:
    return PluginManifest(
        name="Hello Plugin",
        id="hello",
        version="1.0.0",
        description="Minimal example plugin that renders a themed greeting.",
        author="UnchartedAli",
        source="built-in",
        category="Plugins",
        tags=["example"],
        commands=["hello"],
        permissions=["telegram.message"],
        config={
            "greeting": {"type": "string", "default": "Hello from a Reze plugin", "description": "Text sent by .hello"}
        },
    )


__all__ = [
    "CAPABILITIES",
    "PluginManifest",
    "build_manifest",
    "example_manifest",
    "is_compatible",
    "parse_version",
]
