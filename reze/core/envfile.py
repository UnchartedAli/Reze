"""
Tiny, dependency-free ``.env`` editor used by ``.setvar`` / ``.getvar`` / ``.delvar``.

* Only ``REZE_*`` names are accepted, so the commands can never be used to change
  ``PATH``, ``LD_PRELOAD`` or any other process-level variable.
* Secret-looking values are masked whenever they are displayed.
* Writes are atomic (temp file + rename) and keep comments and ordering intact.
"""

import os
import re
import tempfile
from typing import Dict, List, Optional, Tuple

KEY_RE = re.compile(r"^REZE_[A-Z0-9_]{2,60}$")
SECRET_HINTS = ("HASH", "SESSION", "KEY", "PASSWORD", "SECRET", "TOKEN")
_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


class EnvFileError(ValueError):
    """Invalid variable name or value."""


def valid_key(key: str) -> str:
    key = (key or "").strip().upper()
    if not KEY_RE.match(key):
        raise EnvFileError("Variable names must look like REZE_SOMETHING (A-Z, 0-9, _).")
    return key


def valid_value(value: str) -> str:
    if "\n" in value or "\r" in value or "\x00" in value:
        raise EnvFileError("Values cannot contain line breaks or NUL characters.")
    if len(value) > 2000:
        raise EnvFileError("Value is too long (2000 characters max).")
    return value


def is_secret(key: str) -> bool:
    upper = key.upper()
    return any(hint in upper for hint in SECRET_HINTS)


def mask(value: str) -> str:
    if not value:
        return "(empty)"
    tail = value[-4:] if len(value) > 8 else ""
    return "*" * 8 + tail


def display(key: str, value: str) -> str:
    return mask(value) if is_secret(key) else (value if value != "" else "(empty)")


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")  # undo what _quote() escaped
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    if " #" in raw:  # inline comment on an unquoted value
        raw = raw.split(" #", 1)[0].rstrip()
    return raw


def _quote(value: str) -> str:
    if value == "" or re.search(r"[\s#'\"\\$]", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def read(path: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = _LINE_RE.match(line.rstrip("\n"))
                if match and not line.lstrip().startswith("#"):
                    values[match.group(1)] = _unquote(match.group(2))
    except FileNotFoundError:
        pass
    return values


def _atomic_write(path: str, lines: List[str]) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip("\n") + "\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read_lines(path: str) -> List[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().splitlines()
    except FileNotFoundError:
        return []


def set_value(path: str, key: str, value: str) -> Tuple[str, bool]:
    """Set *key* in the file. Returns ``(key, replaced_existing)``."""
    key = valid_key(key)
    value = valid_value(value)
    lines = _read_lines(path)
    replaced = False
    out: List[str] = []
    for line in lines:
        match = _LINE_RE.match(line)
        if match and match.group(1) == key and not line.lstrip().startswith("#"):
            if not replaced:
                out.append(f"{key}={_quote(value)}")
                replaced = True
            continue  # drop duplicates
        out.append(line)
    if not replaced:
        out.append(f"{key}={_quote(value)}")
    _atomic_write(path, out)
    return key, replaced


def delete_value(path: str, key: str) -> bool:
    key = valid_key(key)
    lines = _read_lines(path)
    out = [
        line for line in lines
        if not ((m := _LINE_RE.match(line)) and m.group(1) == key and not line.lstrip().startswith("#"))
    ]
    if len(out) == len(lines):
        return False
    _atomic_write(path, out)
    return True


def listing(path: str) -> List[Tuple[str, str]]:
    return [(k, display(k, v)) for k, v in read(path).items() if KEY_RE.match(k)]
