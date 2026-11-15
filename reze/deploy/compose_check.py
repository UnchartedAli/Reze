"""Offline Docker Compose checker for Cloady and VPS deployments.

The rules come from Cloady's public material and from how REZE runs. Each finding
states its source, so you can tell documented rules from conservative guesses:

* ``[cloady-docs]``: stated in Cloady's public templates repository
  (github.com/Cloady/templates): ``ports:`` are public, ``expose:`` is private,
  volume size comes from ``driver_opts.size``, ``env_file`` receives app
  variables at deploy time, and ``depends_on`` is ignored.
* ``[cloady-samples]``: stated in github.com/Cloady/samples: every app listens on
  ``PORT``, and native compose templates support ``${VAR}`` interpolation.
* ``[reze]``: REZE's own requirements (one Telegram session per instance, the
  panel port, no committed secrets).
* ``[heuristic]``: a conservative check that Cloady may or may not enforce.
  Confirm it on your first deploy.

This module does not call Cloady. It reads a file and reports problems.

Usage::

    python -m reze.deploy.compose_check [path/to/docker-compose.yml]

Exit status is 1 when any error is found.

Developer: UnchartedAli · Channel: @yamods
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

ERROR = "error"
WARNING = "warning"
INFO = "info"

_NAMED_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SECRET_HINTS = ("SESSION", "PASSWORD", "SECRET", "TOKEN", "API_HASH", "API_KEY", "_KEY")
_INTERPOLATION = re.compile(r"\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*")
_REFERENCE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::?[-?][^}]*)?\}|\$[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class Finding:
    level: str
    code: str
    service: Optional[str]
    message: str
    suggestion: str
    source: str


class ComposeCheckError(Exception):
    """Raised when the file cannot be read or is not a Compose mapping."""


@dataclass
class Report:
    path: str
    findings: List[Finding]

    @property
    def ok(self) -> bool:
        return not any(f.level == ERROR for f in self.findings)

    def to_dicts(self) -> List[Dict[str, Any]]:
        return [asdict(f) for f in self.findings]

    def to_text(self) -> str:
        if not self.findings:
            return f"{self.path}: no problems found."
        lines = [f"{self.path}:"]
        for f in self.findings:
            where = f" [{f.service}]" if f.service else ""
            lines.append(f"  {f.level.upper():7} {f.code}{where}: {f.message}")
            lines.append(f"          fix: {f.suggestion}  (source: {f.source})")
        errors = sum(1 for f in self.findings if f.level == ERROR)
        warnings = sum(1 for f in self.findings if f.level == WARNING)
        lines.append(f"  result: {'PASS' if self.ok else 'FAIL'} ({errors} error(s), {warnings} warning(s))")
        return "\n".join(lines)


# ----------------------------------------------------------------- loading
def load_compose(path: str) -> Dict[str, Any]:
    """Parse a Compose file. Needs PyYAML (``pip install pyyaml``)."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ComposeCheckError("PyYAML is required: pip install pyyaml") from exc
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        raise ComposeCheckError(f"Cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ComposeCheckError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
        raise ComposeCheckError(f"{path} has no 'services' mapping.")
    return data


# ------------------------------------------------------------------- rules
def _is_named(source: str) -> bool:
    return bool(_NAMED_VOLUME.match(source))


def _volume_items(service: Dict[str, Any]) -> Iterable[Tuple[int, Any]]:
    for index, entry in enumerate(service.get("volumes") or []):
        yield index, entry


def _check_volumes(
    name: str, service: Dict[str, Any], declared: Dict[str, Any], findings: List[Finding]
) -> None:
    for index, entry in _volume_items(service):
        source: Optional[str]
        target: Optional[str]
        shown = entry
        if isinstance(entry, str):
            parts = entry.split(":")
            if len(parts) < 2:
                findings.append(
                    Finding(
                        ERROR,
                        "VOLUME-ANONYMOUS",
                        name,
                        f"volumes[{index}] '{entry}' is an anonymous volume.",
                        "Declare a named volume at the top level and mount it as name:/path.",
                        "[cloady-docs]",
                    )
                )
                continue
            source, target = parts[0], parts[1]
        elif isinstance(entry, dict):
            kind = str(entry.get("type", "volume"))
            source, target = entry.get("source"), entry.get("target")
            if kind == "bind":
                source = source or "(bind)"
                shown = f"type=bind source={source} target={target}"
            if not source:
                findings.append(
                    Finding(
                        ERROR,
                        "VOLUME-ANONYMOUS",
                        name,
                        f"volumes[{index}] has no source.",
                        "Declare a named volume at the top level and reference it by name.",
                        "[cloady-docs]",
                    )
                )
                continue
            if kind == "bind":
                findings.append(_bind_finding(name, index, shown, target))
                continue
        else:
            continue

        if not _is_named(str(source)):
            findings.append(_bind_finding(name, index, shown, target))
            continue
        if source not in declared:
            findings.append(
                Finding(
                    ERROR,
                    "VOLUME-UNDECLARED",
                    name,
                    f"volumes[{index}] mounts '{source}', which is not declared at the top level.",
                    f"Add '{source}:' under the top-level volumes: key.",
                    "[cloady-docs]",
                )
            )


def _bind_finding(name: str, index: int, shown: Any, target: Any) -> Finding:
    tgt = target or "/path"
    return Finding(
        ERROR,
        "VOLUME-BIND",
        name,
        f"volumes[{index}] '{shown}' is a host bind mount. Cloady: volumes must mount a "
        "declared named volume, as volume:/path.",
        f"Declare a top-level volume (for example reze_data:) and mount it as reze_data:{tgt}. "
        "Named volumes keep data across redeploys.",
        "[cloady-docs]",
    )


def _check_declared_volumes(declared: Dict[str, Any], findings: List[Finding]) -> None:
    for vol_name, spec in declared.items():
        driver_opts = (spec or {}).get("driver_opts") or {}
        if "size" not in driver_opts:
            findings.append(
                Finding(
                    INFO,
                    "VOLUME-SIZE-DEFAULT",
                    None,
                    f"volume '{vol_name}' has no driver_opts.size, so Cloady applies its default disk size.",
                    "Set volumes.<name>.driver_opts.size if you need a specific size. Docker's local driver "
                    "does not accept it, so keep it out of files used for local runs.",
                    "[cloady-docs] [heuristic]",
                )
            )


def _split_port(text: str) -> List[str]:
    """Split a ports string on colons, ignoring colons inside ${...} references."""
    return re.split(r":(?![^{}]*\})", text)


def _is_reference(value: str) -> bool:
    """True when the whole value is one Compose variable reference."""
    return bool(_REFERENCE.fullmatch(value))


def _port_host_part(entry: Any) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(host_ip, host_port)`` for a ports entry; either may be None."""
    if isinstance(entry, dict):
        published = entry.get("published")
        host_ip = entry.get("host_ip")
        return (str(host_ip) if host_ip else None), (str(published) if published is not None else None)
    text = str(entry)
    parts = _split_port(text)
    if len(parts) == 1:
        return None, None
    if len(parts) == 2:
        return None, parts[0]
    return ":".join(parts[:-2]) or None, parts[-2]


def _check_ports(name: str, service: Dict[str, Any], findings: List[Finding]) -> None:
    ports = service.get("ports") or []
    expose = service.get("expose") or []
    if not ports and not expose:
        findings.append(
            Finding(
                WARNING,
                "PORT-NONE",
                name,
                "No ports: or expose: entry, so the panel cannot be reached.",
                "Add ports: for public access (Cloady ports are public).",
                "[cloady-docs]",
            )
        )
    for entry in ports:
        host_ip, host_port = _port_host_part(entry)
        if host_ip and host_ip not in ("0.0.0.0", "::"):
            findings.append(
                Finding(
                    WARNING,
                    "PORT-LOOPBACK",
                    name,
                    f"port '{entry}' binds only to {host_ip}; it is not reachable from outside the host.",
                    "Use the plain form (\"${PORT:-8080}:${PORT:-8080}\") for public access, "
                    "or keep the loopback binding only behind a reverse proxy on the same host.",
                    "[reze] [heuristic]",
                )
            )
        if host_port is not None and not _INTERPOLATION.search(host_port) and host_port.isdigit():
            findings.append(
                Finding(
                    WARNING,
                    "PORT-FIXED",
                    name,
                    f"port '{entry}' uses a fixed host port. Cloady sets the app port through PORT "
                    "and every app must listen on it.",
                    "Use \"${PORT:-8080}:${PORT:-8080}\" so the published port follows PORT, and the "
                    "default still works on a VPS.",
                    "[cloady-samples] [heuristic]",
                )
            )


def _env_items(service: Dict[str, Any]) -> List[Tuple[str, Optional[str]]]:
    env = service.get("environment")
    if isinstance(env, dict):
        return [(str(k), None if v is None else str(v)) for k, v in env.items()]
    if isinstance(env, list):
        items = []
        for raw in env:
            key, _, value = str(raw).partition("=")
            items.append((key, value if "=" in str(raw) else None))
        return items
    return []


def _check_environment(
    name: str, service: Dict[str, Any], base_dir: Optional[str], findings: List[Finding]
) -> None:
    for key, value in _env_items(service):
        if not value:
            continue
        for var in re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?[-?][^}]*)?\}", value):
            findings.append(
                Finding(
                    INFO,
                    "ENV-INTERPOLATED",
                    name,
                    f"{key} takes its value from ${{{var}}} at deploy time.",
                    f"Set {var} as a secret or variable in the Cloady dashboard before deploying.",
                    "[cloady-samples]",
                )
            )
        if _is_reference(value):
            continue
        if "$" in value and "$$" not in value:
            findings.append(
                Finding(
                    WARNING,
                    "DOLLAR-ESCAPE",
                    name,
                    f"{key} contains '$'. Compose reads $name as a variable and may replace it with an empty string.",
                    "Write each literal dollar sign as $$ in the compose file, or move the value into a secret.",
                    "[compose-spec]",
                )
            )
        if any(hint in key.upper() for hint in _SECRET_HINTS):
            findings.append(
                Finding(
                    ERROR,
                    "SECRET-LITERAL",
                    name,
                    f"{key} has a literal value in the compose file. Anyone who can read the repository can read it.",
                    f"Remove the value. Set {key} as a secret in Cloady, or keep it in a .env file that Git ignores.",
                    "[reze]",
                )
            )

    env_file = service.get("env_file")
    if env_file:
        files = [env_file] if isinstance(env_file, str) else [
            item["path"] if isinstance(item, dict) else item for item in env_file
        ]
        for path in files:
            if base_dir is None:
                continue
            if os.path.isfile(os.path.join(base_dir, str(path))):
                continue
            if str(path) == ".env":
                findings.append(
                    Finding(
                        INFO,
                        "ENVFILE-MISSING-LOCAL",
                        name,
                        ".env is not in this folder. Cloady supplies app variables to env_file at deploy time.",
                        "For a local run, copy .env.example to .env and fill it in. Never commit .env.",
                        "[cloady-docs]",
                    )
                )
            else:
                findings.append(
                    Finding(
                        ERROR,
                        "ENVFILE-MISSING",
                        name,
                        f"env_file '{path}' does not exist.",
                        "Create the file or correct the path.",
                        "[heuristic]",
                    )
                )


def _check_build(name: str, service: Dict[str, Any], base_dir: Optional[str], findings: List[Finding]) -> None:
    build = service.get("build")
    if not build or base_dir is None:
        return
    context = build if isinstance(build, str) else (build or {}).get("context", ".")
    context_dir = os.path.normpath(os.path.join(base_dir, str(context)))
    if not os.path.isdir(context_dir):
        findings.append(
            Finding(
                ERROR,
                "BUILD-CONTEXT",
                name,
                f"build context '{context}' does not exist.",
                "Point build.context at the folder that contains the Dockerfile.",
                "[heuristic]",
            )
        )
        return
    dockerfile = "Dockerfile" if isinstance(build, str) else (build or {}).get("dockerfile", "Dockerfile")
    if not os.path.isfile(os.path.join(context_dir, str(dockerfile))):
        findings.append(
            Finding(
                ERROR,
                "BUILD-DOCKERFILE",
                name,
                f"Dockerfile '{dockerfile}' not found in '{context}'.",
                "Add the Dockerfile or set build.dockerfile to the correct file.",
                "[heuristic]",
            )
        )


def _check_port_env(name: str, service: Dict[str, Any], findings: List[Finding]) -> None:
    """A service that publishes a PORT-based host port must also give the app that PORT.

    Otherwise the published port and the port the app listens on can differ. This was
    found on a live container run: the host published 3100 while the app listened on 8080.
    """
    published = [str(_port_host_part(entry)[1] or "") for entry in service.get("ports") or []]
    uses_port = [value for value in published if re.search(r"\$\{PORT[:}-]", value)]
    if not uses_port:
        return
    env = dict(_env_items(service))
    value = env.get("PORT")
    if value is None or "PORT" not in env or not re.search(r"\$\{PORT[:}-]", value or ""):
        findings.append(
            Finding(
                WARNING,
                "PORT-NOT-PASSED",
                name,
                "The published port follows PORT, but the container does not receive PORT. "
                "The app would listen on its default port while the host publishes another.",
                'Add PORT: "${PORT:-8080}" under environment, so the app and the published port match.',
                "[reze] [verified-run]",
            )
        )


def _check_service_policy(
    name: str, service: Dict[str, Any], single_instance: bool, findings: List[Finding]
) -> None:
    if service.get("depends_on"):
        findings.append(
            Finding(
                WARNING,
                "DEPENDS-ON-IGNORED",
                name,
                "depends_on is ignored by Cloady, so services may start in any order.",
                "Make each service tolerate a dependency that is not ready yet, or wait for it in the entrypoint.",
                "[cloady-templates]",
            )
        )
    replicas = (service.get("deploy") or {}).get("replicas", 1)
    try:
        replica_count = int(replicas)
    except (TypeError, ValueError):
        replica_count = 1
    if single_instance and replica_count != 1:
        findings.append(
            Finding(
                ERROR,
                "REPLICAS-NOT-ONE",
                name,
                f"deploy.replicas is {replicas}. REZE must run exactly one instance; two instances would "
                "connect the same Telegram session twice.",
                "Set deploy.replicas to 1, or remove the key.",
                "[reze]",
            )
        )
    if "healthcheck" not in service:
        findings.append(
            Finding(
                INFO,
                "HEALTHCHECK-MISSING",
                name,
                "No healthcheck is defined.",
                "Add a healthcheck so the platform can detect a stuck process.",
                "[reze] [heuristic]",
            )
        )


def _check_repository(base_dir: Optional[str], findings: List[Finding]) -> None:
    if base_dir is None:
        return
    gitignore = os.path.join(base_dir, ".gitignore")
    if os.path.isfile(os.path.join(base_dir, ".env")):
        ignored = False
        if os.path.isfile(gitignore):
            with open(gitignore, "r", encoding="utf-8", errors="replace") as handle:
                ignored = any(line.strip() in (".env", "/.env") for line in handle)
        if not ignored:
            findings.append(
                Finding(
                    ERROR,
                    "ENV-NOT-IGNORED",
                    None,
                    ".env exists in the project folder and .gitignore does not exclude it.",
                    "Add '.env' to .gitignore before committing, and rotate any secret that was already committed.",
                    "[reze]",
                )
            )
    has_dockerfile = os.path.isfile(os.path.join(base_dir, "Dockerfile"))
    if has_dockerfile:
        findings.append(
            Finding(
                INFO,
                "DEPLOY-PATH-AMBIGUOUS",
                None,
                "The project has both a Dockerfile and a compose file.",
                "Cloady's public samples show a Dockerfile build and a compose template as separate "
                "paths. Confirm in the Cloady dashboard which one it uses for this app.",
                "[cloady-samples] [heuristic]",
            )
        )


# -------------------------------------------------------------------- API
def check(
    data: Dict[str, Any],
    base_dir: Optional[str] = None,
    *,
    path: str = "docker-compose.yml",
    single_instance: bool = True,
) -> Report:
    """Check an already-parsed Compose mapping.

    *base_dir* is the folder the file lives in. It is needed for file-existence
    checks. Without it, those checks are skipped.
    """
    findings: List[Finding] = []
    services = data.get("services") or {}
    declared = data.get("volumes") or {}
    if not isinstance(services, dict):
        raise ComposeCheckError("'services' must be a mapping.")
    if not isinstance(declared, dict):
        declared = {}

    for name, service in services.items():
        if not isinstance(service, dict):
            raise ComposeCheckError(f"Service '{name}' must be a mapping.")
        _check_volumes(name, service, declared, findings)
        _check_ports(name, service, findings)
        _check_port_env(name, service, findings)
        _check_environment(name, service, base_dir, findings)
        _check_build(name, service, base_dir, findings)
        _check_service_policy(name, service, single_instance, findings)

    _check_declared_volumes(declared, findings)
    _check_repository(base_dir, findings)
    return Report(path=path, findings=findings)


def check_file(path: str, *, single_instance: bool = True) -> Report:
    data = load_compose(path)
    return check(
        data,
        base_dir=os.path.dirname(os.path.abspath(path)),
        path=path,
        single_instance=single_instance,
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    target = args[0] if args else "docker-compose.yml"
    try:
        report = check_file(target)
    except ComposeCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(report.to_text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
