from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from pydantic import Field, JsonValue, computed_field

from web_app.core.canonical import canonical_digest
from web_app.core.contracts import FrozenContract


class CapabilityDefinition(FrozenContract):
    capability_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: Mapping[str, JsonValue]
    effect_class: str
    approval_class: str
    prerequisites: tuple[str, ...] = ()
    supported_project_types: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    rollback_class: str
    adapter_id: str
    adapter_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @computed_field
    @property
    def definition_digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json", exclude={"definition_digest"}))


class CapabilityAvailability(FrozenContract):
    definition: CapabilityDefinition
    available: bool
    reasons: tuple[str, ...] = ()


class CapabilityCatalog:
    def __init__(self, definitions: Iterable[CapabilityDefinition], *, probed_adapters: Set[str]) -> None:
        self.definitions = tuple(definitions)
        ids = [item.capability_id for item in self.definitions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate capability id")
        self._probed = frozenset(probed_adapters)

    def list_for_project(self, project_types: Set[str]) -> tuple[CapabilityAvailability, ...]:
        result = []
        for definition in self.definitions:
            reasons = []
            if definition.adapter_id not in self._probed:
                reasons.append("adapter was not probed")
            missing = sorted(set(definition.prerequisites) - set(project_types))
            if missing:
                reasons.append("missing prerequisites: " + ", ".join(missing))
            if definition.supported_project_types and not set(definition.supported_project_types) & set(project_types):
                reasons.append("project type is unsupported")
            result.append(CapabilityAvailability(definition=definition, available=not reasons, reasons=tuple(reasons)))
        return tuple(result)

    def planner_schema(self, project_types: Set[str]) -> dict:
        available = [item.definition.capability_id for item in self.list_for_project(project_types) if item.available]
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "done": {"type": "boolean"},
                "capability_id": {"type": "string", "enum": available},
                "operation": {"type": "string", "minLength": 1},
                "target_path": {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["done", "capability_id", "operation", "target_path", "arguments"],
        }


_LIFECYCLE_CAPABILITIES = {
    "project.read": ("read", "automatic", (), "none"),
    "project.search": ("read", "automatic", (), "none"),
    "project.patch": ("file_change", "exact", (), "checkpoint"),
    "native.read": ("read", "automatic", (), "none"),
    "native.write": ("file_change", "exact", (), "checkpoint"),
    "native.edit": ("file_change", "exact", (), "checkpoint"),
    "native.shell": ("command", "exact", (), "worktree"),
    "terminal.session": ("command", "exact", (), "process"),
    "terminal.execute": ("command", "exact", (), "process"),
    "terminal.interrupt": ("process_control", "exact", (), "none"),
    "terminal.close": ("process_control", "exact", (), "none"),
    "checkpoint.create": ("local_state", "exact", (), "none"),
    "checkpoint.restore": ("file_change", "exact", (), "checkpoint"),
    "git.execute": ("git_effect", "exact", ("git",), "git"),
    "inference.generate": ("inference", "automatic", (), "none"),
    "component.install": ("installation", "exact", (), "uninstall"),
    "component.execute": ("extension", "exact", (), "adapter"),
    "code.refactor": ("file_change", "exact", (), "checkpoint"),
    "code.debug": ("command", "exact", (), "worktree"),
    "code.document": ("file_change", "exact", (), "checkpoint"),
    "code.review": ("read", "automatic", (), "none"),
    "build.run": ("command", "exact", (), "worktree"),
    "test.run": ("command", "exact", (), "worktree"),
    "lint.run": ("command", "exact", (), "worktree"),
    "format.run": ("file_change", "exact", (), "worktree"),
    "typecheck.run": ("command", "exact", (), "worktree"),
    "package.build": ("command", "exact", (), "worktree"),
    "benchmark.run": ("command", "exact", (), "worktree"),
    "application.run": ("command", "exact", (), "process"),
    "dependency.audit": ("network", "exact", (), "none"),
    "dependency.update": ("installation", "exact", (), "worktree"),
    "license.audit": ("read", "automatic", (), "none"),
    "vulnerability.scan": ("network", "exact", (), "none"),
    "service.manage": ("service", "exact", (), "process"),
    "database.manage": ("external_effect", "exact", ("database",), "backup"),
    "container.manage": ("external_effect", "exact", ("containers",), "container"),
    "browser.test": ("command", "exact", ("browser",), "worktree"),
    "api.test": ("network", "exact", (), "none"),
    "desktop.test": ("command", "exact", (), "process"),
    "mcp.manage": ("external_effect", "exact", (), "adapter"),
    "lsp.inspect": ("read", "automatic", (), "none"),
    "debugger.run": ("command", "exact", (), "process"),
    "profiler.run": ("command", "exact", (), "process"),
    "infrastructure.preview": ("network", "exact", (), "none"),
    "infrastructure.apply": ("infrastructure", "strong_exact", (), "provider_rollback"),
    "deployment.preview": ("network", "exact", (), "none"),
    "deployment.apply": ("deployment", "strong_exact", (), "deployment_rollback"),
    "deployment.health": ("read_network", "exact", (), "none"),
    "deployment.logs": ("read_network", "exact", (), "none"),
    "deployment.rollback": ("deployment", "strong_exact", (), "deployment_rollback"),
}


def lifecycle_definitions() -> tuple[CapabilityDefinition, ...]:
    schema = {"type": "object", "additionalProperties": True}
    definitions = []
    for capability_id, (effect, approval, prerequisites, rollback) in _LIFECYCLE_CAPABILITIES.items():
        adapter_digest = canonical_digest({"adapter": capability_id, "version": "1"})
        definitions.append(CapabilityDefinition(
            capability_id=capability_id, version="1",
            description=capability_id.replace(".", " "), input_schema=schema,
            effect_class=effect, approval_class=approval,
            prerequisites=prerequisites, rollback_class=rollback,
            adapter_id=capability_id, adapter_digest=adapter_digest,
        ))
    return tuple(definitions)
