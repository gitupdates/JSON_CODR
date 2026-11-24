from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping


_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PATH = _REPOSITORY_ROOT / "config" / "runtime.json"
_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "version",
        "host",
        "port",
        "api_paths",
        "python",
        "default_roots",
        "allowed_environment_overrides",
    }
)
_API_PATH_KEYS = frozenset({"health", "runtime_status", "tasks"})
_PYTHON_KEYS = frozenset({"host_versions", "compatible_versions"})
_ROOT_KEYS = frozenset({"data_root_segment", "launcher_root_segment"})


@dataclass(frozen=True)
class RuntimeConfig:
    schema_version: str
    version: str
    host: str
    port: int
    health_path: str
    runtime_status_path: str
    tasks_path: str
    host_python_versions: tuple[str, ...]
    compatible_python_versions: tuple[str, ...]
    data_root_segment: str
    launcher_root_segment: str
    allowed_environment_overrides: frozenset[str]
    environment_overrides: tuple[tuple[str, str], ...]

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @classmethod
    def load(cls, path: Path | None = None) -> "RuntimeConfig":
        config_path = path or _DEFAULT_PATH
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ValueError(f"unable to read runtime configuration: {config_path}") from error
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid runtime configuration JSON: {config_path}") from error
        if not isinstance(raw, dict):
            raise ValueError("runtime configuration must be an object")
        _require_exact_keys(raw, _REQUIRED_KEYS, "runtime configuration")

        allowed = _string_set(raw["allowed_environment_overrides"], "allowed_environment_overrides")
        environment_overrides = _validated_environment_overrides(allowed)
        api_paths = _object(raw["api_paths"], "api_paths")
        _require_exact_keys(api_paths, _API_PATH_KEYS, "api_paths")
        python = _object(raw["python"], "python")
        _require_exact_keys(python, _PYTHON_KEYS, "python")
        roots = _object(raw["default_roots"], "default_roots")
        _require_exact_keys(roots, _ROOT_KEYS, "default_roots")

        schema_version = _string(raw["schema_version"], "schema_version")
        version = _string(raw["version"], "version")
        host = _string(raw["host"], "host")
        port = raw["port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        health_path = _api_path(api_paths["health"], "api_paths.health")
        runtime_status_path = _api_path(api_paths["runtime_status"], "api_paths.runtime_status")
        tasks_path = _api_path(api_paths["tasks"], "api_paths.tasks")
        host_python_versions = _versions(python["host_versions"], "python.host_versions")
        compatible_python_versions = _versions(python["compatible_versions"], "python.compatible_versions")
        data_root_segment = _path_segment(roots["data_root_segment"], "default_roots.data_root_segment")
        launcher_root_segment = _path_segment(roots["launcher_root_segment"], "default_roots.launcher_root_segment")
        return cls(
            schema_version=schema_version,
            version=version,
            host=host,
            port=port,
            health_path=health_path,
            runtime_status_path=runtime_status_path,
            tasks_path=tasks_path,
            host_python_versions=host_python_versions,
            compatible_python_versions=compatible_python_versions,
            data_root_segment=data_root_segment,
            launcher_root_segment=launcher_root_segment,
            allowed_environment_overrides=allowed,
            environment_overrides=environment_overrides,
        )

    def receipt_digest(self) -> str:
        document = {
            "schema_version": self.schema_version,
            "version": self.version,
            "host": self.host,
            "port": self.port,
            "api_paths": {
                "health": self.health_path,
                "runtime_status": self.runtime_status_path,
                "tasks": self.tasks_path,
            },
            "python": {
                "host_versions": self.host_python_versions,
                "compatible_versions": self.compatible_python_versions,
            },
            "default_roots": {
                "data_root_segment": self.data_root_segment,
                "launcher_root_segment": self.launcher_root_segment,
            },
            "allowed_environment_overrides": sorted(self.allowed_environment_overrides),
            "environment_overrides": self.environment_overrides,
        }
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return sha256(encoded).hexdigest()


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown:
        raise ValueError(f"unknown {label} keys: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"missing {label} keys: {', '.join(missing)}")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _api_path(value: Any, label: str) -> str:
    value = _string(value, label)
    if not value.startswith("/") or "//" in value:
        raise ValueError(f"{label} must be an absolute API path")
    return value


def _versions(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    versions = tuple(_string(item, label) for item in value)
    if any(not version.replace(".", "").isdigit() for version in versions):
        raise ValueError(f"{label} must contain Python versions")
    return versions


def _path_segment(value: Any, label: str) -> str:
    value = _string(value, label)
    if Path(value).name != value or value in {".", ".."}:
        raise ValueError(f"{label} must be a single path segment")
    return value


def _string_set(value: Any, label: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    names = tuple(_string(item, label) for item in value)
    if len(set(names)) != len(names) or any(not name.startswith("JSON_CODR_") for name in names):
        raise ValueError(f"{label} must contain unique JSON_CODR environment variable names")
    return frozenset(names)


def _validated_environment_overrides(allowed: frozenset[str]) -> tuple[tuple[str, str], ...]:
    overrides = {name: value for name, value in os.environ.items() if name.startswith("JSON_CODR_") and value}
    unknown = sorted(set(overrides) - allowed)
    if unknown:
        raise ValueError(f"undeclared environment override: {', '.join(unknown)}")
    return tuple(sorted(overrides.items()))
