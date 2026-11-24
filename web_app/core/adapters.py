from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Protocol

from pydantic import Field, JsonValue, field_validator

from web_app.core.contracts import ExecutionMode, FrozenContract, ProjectId, TaskId


class CapabilityCall(FrozenContract):
    capability_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    project_root: str = Field(min_length=1)
    target_path: str | None = None
    mode: ExecutionMode = ExecutionMode.native
    privacy_boundary: str = "local"
    approved_privacy_boundary: str = "local"
    cost_boundary: str = "local"
    approved_cost_boundary: str = "local"
    schedule_id: str | None = None
    credential_refs: tuple[str, ...] = ()
    arguments: Mapping[str, JsonValue] = Field(default_factory=dict)

    @field_validator("credential_refs")
    @classmethod
    def validate_credential_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.startswith("credential:") for item in value):
            raise ValueError("credentials must be opaque references")
        return value


class ExecutionContext(FrozenContract):
    task_id: TaskId
    project_id: ProjectId
    principal: str
    principal_scopes: tuple[str, ...] = ()
    credential_refs: tuple[str, ...] = ()


class AdapterEvent(FrozenContract):
    event_type: str = Field(min_length=1)
    payload: Mapping[str, JsonValue] = Field(default_factory=dict)


class CapabilityExecutionError(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class CapabilityAdapter(Protocol):
    def execute(self, call: CapabilityCall, context: ExecutionContext) -> AsyncIterator[AdapterEvent]: ...
