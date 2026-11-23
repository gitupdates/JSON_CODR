from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from urllib.request import urlopen


DEFAULT_SERVICE_URL = "http://127.0.0.1:8765"


def default_manifest_path(environment: Mapping[str, str] | None = None) -> Path:
    values = environment if environment is not None else os.environ
    local = values.get("LOCALAPPDATA")
    if local:
        return Path(local) / "JSON_CODR" / "installation.json"
    return Path.home() / ".json_codr" / "installation.json"


@dataclass(frozen=True)
class InstallationManifest:
    root: Path
    service_url: str = DEFAULT_SERVICE_URL
    schema_version: int = 1

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "root": str(self.root),
            "service_url": self.service_url,
        }


@dataclass(frozen=True)
class InstallationResolution:
    root: Path
    service_url: str
    source: str
    warnings: tuple[str, ...] = ()


def _valid_root(candidate: Path) -> bool:
    return (
        candidate.is_dir()
        and (candidate / "run_web.ps1").is_file()
        and (candidate / "web_app" / "integrations" / "mcp_server.py").is_file()
    )


def _read_manifest(path: Path) -> InstallationManifest | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            return None
        return InstallationManifest(
            root=Path(payload["root"]).expanduser().resolve(),
            service_url=str(payload.get("service_url") or DEFAULT_SERVICE_URL).rstrip("/"),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


class InstallationResolver:
    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        manifest_path: Path | None = None,
        plugin_root: Path | None = None,
        known_roots: Sequence[Path] = (),
    ):
        self.environment = environment if environment is not None else os.environ
        self.manifest_path = Path(manifest_path) if manifest_path else default_manifest_path(self.environment)
        self.plugin_root = Path(plugin_root).resolve() if plugin_root else None
        self.known_roots = tuple(Path(root).expanduser().resolve() for root in known_roots)

    def resolve(self, explicit_root: str | None = None) -> InstallationResolution:
        warnings: list[str] = []
        manifest = _read_manifest(self.manifest_path)
        candidates: list[tuple[str, Path, str]] = []
        if explicit_root:
            candidates.append(("explicit", Path(explicit_root).expanduser().resolve(), DEFAULT_SERVICE_URL))
        environment_root = self.environment.get("JSON_CODR_ROOT")
        if environment_root:
            candidates.append(("environment", Path(environment_root).expanduser().resolve(), DEFAULT_SERVICE_URL))
        if manifest:
            candidates.append(("manifest", manifest.root, manifest.service_url))
            if not _valid_root(manifest.root):
                warnings.append("stale_manifest")
        if self.plugin_root:
            candidates.append(("plugin", self.plugin_root.parents[1], DEFAULT_SERVICE_URL))
        candidates.extend(("known", root, DEFAULT_SERVICE_URL) for root in self.known_roots)

        for source, root, service_url in candidates:
            if _valid_root(root):
                return InstallationResolution(root, service_url, source, tuple(warnings))
        raise FileNotFoundError("A valid JSON_CODR installation was not found")


def register_installation(
    root: Path,
    service_url: str = DEFAULT_SERVICE_URL,
    *,
    manifest_path: Path | None = None,
) -> InstallationManifest:
    resolved = Path(root).expanduser().resolve()
    if not _valid_root(resolved):
        raise ValueError(f"Invalid JSON_CODR installation: {resolved}")
    manifest = InstallationManifest(resolved, service_url.rstrip("/"))
    destination = Path(manifest_path) if manifest_path else default_manifest_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest.as_json(), indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return manifest


def service_matches_installation(service_url: str, *, timeout_seconds: float = 2.0) -> bool:
    try:
        with urlopen(f"{service_url.rstrip('/')}/.well-known/json-codr", timeout=timeout_seconds) as response:
            discovery = json.load(response)
        with urlopen(f"{service_url.rstrip('/')}/api/health", timeout=timeout_seconds) as response:
            health = json.load(response)
        return discovery.get("service", {}).get("name") == "JSON_CODR" and health.get("status") == "ready"
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
