from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from web_app.core.component_acquisition import AcquiredComponent
from web_app.core.component_registry import ComponentPlan, ComponentRegistry, ComponentRequest, ComponentScope

_COMMAND_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ComponentInspector:
    def __init__(self, registry: ComponentRegistry) -> None:
        self.registry = registry

    def inspect(
        self,
        acquired: AcquiredComponent,
        scope: ComponentScope,
        *,
        project_id: str | None = None,
    ) -> ComponentPlan:
        root = Path(acquired.source_root)
        runtime_kind = "resource"
        entry_points: tuple[str, ...] = ()
        effects: tuple[str, ...] = ()
        executable = False

        pyproject = _first(root, "pyproject.toml")
        package_json = _first(root, "package.json")
        mcp_manifest = _first(root, "mcp_servers.json")
        executables = tuple(path for path in root.iterdir() if path.is_file() and path.suffix.casefold() in {".exe", ".cmd", ".bat"})
        if pyproject is not None:
            document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            scripts = document.get("project", {}).get("scripts", {})
            entry_points = _validated_commands(scripts)
            runtime_kind = "python"
            executable = bool(entry_points)
            effects = ("filesystem_write", "dependency_network", "build_hook")
        elif package_json is not None:
            document = json.loads(package_json.read_text(encoding="utf-8"))
            bins = document.get("bin", {})
            if isinstance(bins, str):
                bins = {str(document.get("name", "component")): bins}
            entry_points = _validated_commands(bins) if isinstance(bins, dict) else ()
            runtime_kind = "node"
            executable = bool(entry_points)
            effects = ("filesystem_write", "dependency_network", "build_hook")
        elif mcp_manifest is not None:
            document = json.loads(mcp_manifest.read_text(encoding="utf-8"))
            servers = document.get("mcpServers", {})
            entry_points = _validated_commands(servers) if isinstance(servers, dict) else ()
            runtime_kind = "mcp"
            executable = bool(entry_points)
            effects = ("filesystem_write", "process_launch")
        elif executables:
            entry_points = tuple(sorted(path.stem for path in executables))
            runtime_kind = "executable"
            executable = True
            effects = ("filesystem_write", "process_launch")

        request = ComponentRequest(
            source_kind=acquired.source_kind,
            source=acquired.canonical_source,
            requested_version=acquired.revision or acquired.requested_version,
            scope=scope,
            project_id=project_id,
        )
        return self.registry.plan(
            request,
            content_digest=acquired.content_digest,
            effects=effects,
            executable=executable,
            entry_points=entry_points,
            runtime_kind=runtime_kind,
        )


def _first(root: Path, name: str) -> Path | None:
    direct = root / name
    if direct.is_file():
        return direct
    matches = sorted(root.glob(f"*/{name}"))
    return matches[0] if matches else None


def _validated_commands(mapping: dict) -> tuple[str, ...]:
    names = tuple(sorted(str(name) for name in mapping))
    if any(not _COMMAND_NAME.fullmatch(name) for name in names):
        raise ValueError("component command names must be portable identifiers")
    return names
