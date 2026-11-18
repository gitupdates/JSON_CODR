from __future__ import annotations

import json
from pathlib import Path

from web_app.core.component_registry import ComponentRegistry
from web_app.core.contracts import FrozenContract


class CatalogComponent(FrozenContract):
    component_id: str
    generation: int
    runtime_kind: str
    runtime_root: str
    commands: dict[str, tuple[str, ...]]
    brokered: bool = True


class ComponentCatalog:
    def __init__(self, registry: ComponentRegistry) -> None:
        self.registry = registry

    def resolve_components(self, project_id: str) -> tuple[CatalogComponent, ...]:
        result = []
        for activation in self.registry.activations(project_id):
            generation = self.registry.generation(activation.component_id, activation.generation)
            if generation.state != "verified" or not generation.runtime_root:
                continue
            manifest = Path(generation.runtime_root) / "runtime.json"
            commands = {}
            if manifest.is_file():
                commands = {name: tuple(argv) for name, argv in json.loads(manifest.read_text(encoding="utf-8")).items()}
            result.append(CatalogComponent(
                component_id=activation.component_id, generation=activation.generation,
                runtime_kind=generation.runtime_kind, runtime_root=generation.runtime_root, commands=commands,
            ))
        return tuple(result)


def active_component_command(root: str | Path, command_name: str) -> tuple[str, ...] | None:
    registry_path = Path(root) / "registry.sqlite"
    if not registry_path.is_file():
        return None
    registry = ComponentRegistry(registry_path)
    try:
        return next((
            component.commands[command_name]
            for component in ComponentCatalog(registry).resolve_components("")
            if command_name in component.commands
        ), None)
    finally:
        registry.close()
