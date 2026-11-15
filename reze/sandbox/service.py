"""Chat-side access to isolated plugins. Owner-only and OFF by default (feature ``isolated_plugins``).

Plugin files live in ``<data_dir>/isolated_plugins/``. Chat never supplies a path. It supplies
a name, which must match ``[a-z][a-z0-9_]{0,31}``, and the file is resolved inside that folder.
A symlink that points elsewhere is refused. The in-process loader never scans this folder, so an
isolated plugin cannot also run inside the bot's process.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

from reze.config import settings
from reze.sandbox.isolation import IsolatedPluginHost, file_sha256

ISOLATED_DIRNAME = "isolated_plugins"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

isolated_host = IsolatedPluginHost()


def isolated_dir() -> str:
    return os.path.join(settings.data_dir or "data", ISOLATED_DIRNAME)


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name or ""))


def resolve_plugin_path(name: str) -> str:
    """The real path of ``<name>.py`` inside the isolated folder. Raises ValueError on any doubt."""
    if not valid_name(name):
        raise ValueError("Use a name of lowercase letters, digits and underscores, starting with a letter.")
    base = os.path.realpath(isolated_dir())
    candidate = os.path.realpath(os.path.join(base, name + ".py"))
    if os.path.dirname(candidate) != base:
        raise ValueError("That plugin file is outside the isolated plugins folder.")
    if not os.path.isfile(candidate):
        raise ValueError(f"No file named {name}.py in the isolated plugins folder.")
    return candidate


def list_plugin_names() -> List[str]:
    folder = isolated_dir()
    if not os.path.isdir(folder):
        return []
    names = []
    for entry in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(entry)
        if ext == ".py" and valid_name(stem) and os.path.isfile(os.path.join(folder, entry)):
            names.append(stem)
    return names


def plugin_status(name: str, path: Optional[str] = None) -> str:
    """One word for the owner: loaded, approved, changed, or not approved."""
    if name in isolated_host.plugins:
        return "loaded"
    try:
        current_path = path or resolve_plugin_path(name)
    except ValueError:
        return "missing"
    recorded = isolated_host.approved_hash(name)
    if recorded is None:
        return "not approved"
    if recorded != file_sha256(current_path):
        return "changed"
    return "approved"


__all__ = [
    "NAME_RE",
    "isolated_dir",
    "isolated_host",
    "list_plugin_names",
    "plugin_status",
    "resolve_plugin_path",
    "valid_name",
]
