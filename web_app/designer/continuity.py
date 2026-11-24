from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from web_app.designer.components import ComponentRegistry
from web_app.designer.contracts import DesignDocument
from web_app.designer.json_codr_manifest import FIXED_RUNTIME_CAPABILITIES


REQUIRED_CORE_CAPABILITIES = frozenset(
    {
        "workspace.navigation",
        "identity.auth",
        "task.execute",
        "settings.open",
        "recovery.open",
        "safe_mode.open",
    }
)


class CoreCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str
    source: Literal["design-node", "fixed-runtime"]
    node_id: str | None = None


class ContinuityViolation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    capability: str | None = None
    node_id: str | None = None


def validate_runtime_continuity(
    document: DesignDocument,
    registry: ComponentRegistry,
) -> tuple[ContinuityViolation, ...]:
    available = set(FIXED_RUNTIME_CAPABILITIES)
    violations: list[ContinuityViolation] = []
    for node in document.nodes:
        capability = node.properties.get("core_capability")
        if isinstance(capability, str):
            available.add(capability)
        definition = registry.resolve(node.component_type)
        if definition.inert_placeholder:
            violations.append(
                ContinuityViolation(
                    code="component_unavailable",
                    message=f"{node.component_type} has no approved runtime, migration, or fallback renderer",
                    node_id=node.node_id,
                )
            )
    for capability in sorted(REQUIRED_CORE_CAPABILITIES - available):
        violations.append(
            ContinuityViolation(
                code="core_capability_unreachable",
                message=f"required core capability is unreachable: {capability}",
                capability=capability,
            )
        )
    return tuple(violations)
