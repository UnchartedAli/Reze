"""
Plugin lifecycle manager.

Discovery is deterministic (alphabetical), each plugin is loaded in isolation so
one failure cannot take the userbot down, duplicate command names are rejected,
declared dependencies are checked, and enable/disable state is persisted in
SQLite.

**Isolation honesty:** plugins execute in the same Python process as Reze and
have the same privileges as the userbot itself. Unloading removes the plugin's
commands and references, but Python cannot guarantee that the module released
every task, thread or file handle. Reze therefore never claims that unloading is
a security boundary; see docs/SECURITY.md.
"""

import importlib
import importlib.util
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from reze.command_router import Command, router
from reze.database import db
from reze.exceptions import ManifestError, PluginError
from reze.logging_config import logger
from reze.plugins.manifest import CAPABILITIES, PluginManifest, build_manifest

#: Files in the plugins package that are infrastructure, not plugins.
RESERVED_MODULES = {"__init__", "manifest"}


@dataclass
class PluginState:
    name: str
    path: str
    status: str = "discovered"  # discovered | loaded | disabled | failed
    manifest: Optional[PluginManifest] = None
    commands: List[str] = field(default_factory=list)
    error: str = ""
    loaded_at: float = 0.0
    module: Any = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "path": self.path,
            "commands": list(self.commands),
            "error": self.error,
            "warnings": list(self.warnings),
            "loaded_at": self.loaded_at,
            "manifest": self.manifest.to_dict() if self.manifest else None,
        }

    def can(self, capability: str) -> bool:
        """Advisory capability check (not a security boundary)."""
        return bool(self.manifest and capability in self.manifest.permissions)


class PluginSettings:
    """Typed, validated storage for a plugin's declared configuration."""

    def __init__(self, plugin_id: str, schema: Dict[str, Dict[str, Any]]):
        self.plugin_id = plugin_id
        self.schema = schema or {}

    def _key(self, key: str) -> str:
        return f"plugin:{self.plugin_id}:{key}"

    def _coerce(self, key: str, raw: Any) -> Any:
        spec = self.schema.get(key, {})
        kind = spec.get("type", "string")
        if kind in {"int", "bool"}:
            if kind == "int":
                return int(raw)
            return str(raw).strip().lower() in {"1", "true", "yes", "on"}
        return str(raw)

    def get(self, key: str, default: Any = None) -> Any:
        spec = self.schema.get(key, {})
        if key not in self.schema:
            raise KeyError(f"Plugin '{self.plugin_id}' declares no setting '{key}'.")
        stored = db.get_setting(self._key(key))
        if stored is None:
            return spec.get("default", default)
        try:
            return self._coerce(key, stored)
        except (TypeError, ValueError):
            return spec.get("default", default)

    def set(self, key: str, value: Any) -> None:
        if key not in self.schema:
            raise KeyError(f"Plugin '{self.plugin_id}' declares no setting '{key}'.")
        spec = self.schema[key]
        kind = spec.get("type", "string")
        text = str(value).strip()
        if kind == "int":
            try:
                int(text)
            except ValueError as exc:
                raise ValueError(f"Setting '{key}' must be an integer.") from exc
        elif kind == "bool":
            if text.lower() not in {"0", "1", "true", "false", "yes", "no", "on", "off"}:
                raise ValueError(f"Setting '{key}' must be a boolean.")
            text = "1" if text.lower() in {"1", "true", "yes", "on"} else "0"
        elif kind == "choice":
            choices = [str(choice) for choice in spec.get("choices", [])]
            if text not in choices:
                raise ValueError(f"Setting '{key}' must be one of: {', '.join(choices)}.")
        if len(text) > 4000:
            raise ValueError(f"Setting '{key}' is too long (max 4000 characters).")
        db.set_setting(self._key(key), text)

    def all(self) -> Dict[str, Any]:
        return {key: self.get(key) for key in self.schema}

    def public(self) -> Dict[str, Any]:
        """Values safe to render in the web panel (secrets masked)."""
        result = {}
        for key, spec in self.schema.items():
            value = self.get(key)
            if spec.get("type") == "secret" and value:
                result[key] = "********"
            else:
                result[key] = value
        return result


class PluginManager:
    def __init__(self, plugins_dir: str = "reze/plugins"):
        self.plugins_dir = plugins_dir
        self.states: Dict[str, PluginState] = {}
        self.failures: Dict[str, str] = {}

    # ------------------------------------------------------------- compatibility
    @property
    def loaded_plugins(self) -> Dict[str, Any]:
        return {
            name: state.module
            for name, state in self.states.items()
            if state.status == "loaded" and state.module is not None
        }

    @property
    def plugin_commands(self) -> Dict[str, List[str]]:
        return {
            name: list(state.commands)
            for name, state in self.states.items()
            if state.status == "loaded"
        }

    # ------------------------------------------------------------------ discovery
    def discover(self) -> List[str]:
        if not os.path.isdir(self.plugins_dir):
            return []
        names = []
        for filename in sorted(os.listdir(self.plugins_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            if filename[:-3] in RESERVED_MODULES:
                continue
            names.append(filename[:-3])
        return names

    def is_enabled(self, name: str) -> bool:
        stored = db.get_plugin_enabled(name)
        return True if stored is None else stored

    # --------------------------------------------------------------------- load
    def load(self, name: str, force: bool = False) -> PluginState:
        """Load one plugin, isolating any failure to that plugin."""
        name = name.strip().lower()
        if not name:
            raise PluginError("A plugin name is required.")
        if not force and not self.is_enabled(name):
            raise PluginError(f"Plugin '{name}' is disabled. Enable it first.")

        existing = self.states.get(name)
        if existing and existing.status == "loaded":
            return existing

        path = os.path.join(self.plugins_dir, f"{name}.py")
        if not os.path.isfile(path):
            raise PluginError(f"Plugin file not found: {name}.py")

        before = set(router.commands)
        module_name = f"reze_plugin_{name}"
        sys.modules.pop(module_name, None)

        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise PluginError(f"Could not create an import spec for '{name}'.")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            raw_manifest = getattr(module, "MANIFEST", None)
            if raw_manifest is None:
                raise ManifestError(
                    "No MANIFEST found. Every plugin must export a MANIFEST dictionary."
                )
            manifest = build_manifest(raw_manifest, fallback_id=name)

            self._check_dependencies(manifest)

            registered = sorted(set(router.commands) - before)
            for command_name in registered:
                command: Command = router.commands[command_name]
                command.plugin = name

            missing = [command for command in manifest.commands if command not in registered]
            if missing:
                raise ManifestError(
                    "Manifest declares commands that were not registered: " + ", ".join(missing)
                )
            undeclared = [command for command in registered if command not in manifest.commands]
            for command_name in undeclared:
                command: Command = router.commands[command_name]
                command.category = "Plugins"

            notes = list(manifest.warnings)
            for command_name in undeclared:
                notes.append(f"Registers '.{command_name}' without declaring it in the manifest.")

            state = PluginState(
                name=name,
                path=path,
                status="loaded",
                manifest=manifest,
                commands=registered,
                loaded_at=time.time(),
                module=module,
                warnings=notes,
            )
            self.states[name] = state
            self.failures.pop(name, None)
            db.set_plugin_enabled(name, True, metadata=str(manifest.model_dump())[:2000])
            logger.info(
                "Plugin '%s' v%s loaded (%d commands)", name, manifest.version, len(registered)
            )
            return state

        except Exception as exc:  # noqa: BLE001 - isolate every plugin failure
            self._rollback(name, before)
            error = self._explain(exc, name)
            self.failures[name] = error
            self.states[name] = PluginState(
                name=name, path=path, status="failed", error=error
            )
            logger.error("Plugin '%s' failed to load: %s", name, error)
            raise PluginError(error) from exc

    def _check_dependencies(self, manifest: PluginManifest) -> None:
        missing = [module for module in manifest.requires if importlib.util.find_spec(module) is None]
        if missing:
            raise ManifestError(
                "Missing required dependencies: " + ", ".join(missing) + ". Install them with pip."
            )
        for module in manifest.optional_requires:
            try:
                available = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                available = False
            if not available:
                logger.warning(
                    "Plugin '%s': optional dependency '%s' is not installed.",
                    manifest.id,
                    module,
                )

    @staticmethod
    def _explain(exc: Exception, name: str) -> str:
        if isinstance(exc, (ManifestError, PluginError)):
            return str(exc)
        return f"{type(exc).__name__}: {exc}"

    def _rollback(self, name: str, before: set) -> None:
        """Unregister everything a failed plugin registered."""
        for command_name in list(set(router.commands) - before):
            router.unregister(command_name)
        for command_name in list(router.commands):
            if router.commands[command_name].plugin == name:
                router.unregister(command_name)
        sys.modules.pop(f"reze_plugin_{name}", None)

    def load_all(self) -> Dict[str, PluginState]:
        for name in self.discover():
            if not self.is_enabled(name):
                self.states.setdefault(
                    name,
                    PluginState(
                        name=name,
                        path=os.path.join(self.plugins_dir, f"{name}.py"),
                        status="disabled",
                    ),
                )
                continue
            try:
                self.load(name)
            except PluginError:
                continue  # already recorded in self.failures
        return dict(self.states)

    # ------------------------------------------------------------------- unload
    def unload(self, name: str) -> bool:
        """
        Remove a plugin's commands and references.

        This stops future command dispatch. It cannot force already-running
        tasks started by the plugin to stop, and Python does not guarantee that
        the module released every resource it created.
        """
        name = name.strip().lower()
        state = self.states.get(name)
        if state is None or state.status != "loaded":
            return False
        for command_name in list(router.commands):
            if router.commands[command_name].plugin == name:
                router.unregister(command_name)
        sys.modules.pop(f"reze_plugin_{name}", None)
        state.status = "disabled"
        state.module = None
        state.commands = []
        logger.info("Plugin '%s' unloaded and its commands unregistered.", name)
        return True

    def enable(self, name: str) -> PluginState:
        name = name.strip().lower()
        if not os.path.isfile(os.path.join(self.plugins_dir, f"{name}.py")):
            raise PluginError(f"Plugin file not found: {name}.py")
        db.set_plugin_enabled(name, True)
        return self.load(name, force=True)

    def disable(self, name: str) -> bool:
        name = name.strip().lower()
        self.unload(name)
        db.set_plugin_enabled(name, False)
        state = self.states.get(name)
        if state is not None:
            state.status = "disabled"
        return True

    def reload(self, name: str) -> PluginState:
        self.unload(name)
        return self.load(name, force=True)

    # ---------------------------------------------------------------- inspection
    def get(self, name: str) -> Optional[PluginState]:
        return self.states.get((name or "").strip().lower())

    def settings_for(self, name: str) -> Optional[PluginSettings]:
        state = self.get(name)
        if state is None or state.manifest is None:
            return None
        return PluginSettings(state.manifest.id or state.name, state.manifest.config)

    def status(self) -> Dict[str, Any]:
        loaded = [state for state in self.states.values() if state.status == "loaded"]
        failed = [state for state in self.states.values() if state.status == "failed"]
        disabled = [state for state in self.states.values() if state.status == "disabled"]
        return {
            "total": len(self.states),
            "loaded": len(loaded),
            "failed": len(failed),
            "disabled": len(disabled),
            "plugins": [state.to_dict() for state in sorted(self.states.values(), key=lambda s: s.name)],
            "failures": dict(self.failures),
            "capabilities": CAPABILITIES,
        }


plugin_manager = PluginManager()
