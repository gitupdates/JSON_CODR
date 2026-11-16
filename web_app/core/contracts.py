from __future__ import annotations

import json
from enum import Enum
from typing import Annotated, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_serializer, field_validator, model_validator


Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
TaskId = Identifier
ThreadId = Identifier
ProjectId = Identifier
CommandId = Identifier
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    interrupted = "interrupted"


class ExecutionMode(str, Enum):
    native = "native"
    brokered = "brokered"


class ModelScope(str, Enum):
    independent = "independent"
    allowlist = "allowlist"


class ManifestAuthority(str, Enum):
    host_builtin = "host_builtin"
    verified_provider = "verified_provider"
    quarantined_external = "quarantined_external"


class CapabilityStatus(str, Enum):
    ready = "ready"
    verification_failed = "verification_failed"
    incompatible_platform = "incompatible_platform"
    missing_runtime = "missing_runtime"
    missing_dependency = "missing_dependency"
    missing_model_identity = "missing_model_identity"
    unsupported_route = "unsupported_route"


class FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class VersionedContract(FrozenContract):
    schema_version: Literal["1"] = "1"


class RuntimeIdentity(FrozenContract):
    platform: str = Field(min_length=1)
    runtime_ids: tuple[str, ...] = ()
    model_ids: tuple[str, ...] = ()
    granted_permissions: tuple[str, ...] = ()
    installed_packages: tuple[str, ...] = ()
    runtime_fingerprint: Digest
    hardware_profile_id: Identifier
    hardware_fingerprint: Digest
    model_digests: frozendict[str, Digest]


class CapabilityManifest(VersionedContract):
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
    implementation_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
    version: str = Field(min_length=1)
    modes: tuple[ExecutionMode, ...] = (ExecutionMode.native,)
    platforms: tuple[str, ...] = ()
    runtime_requirements: tuple[str, ...] = ()
    native_models: tuple[str, ...] = ()
    brokered_models: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    required_packages: tuple[str, ...] = ()
    model_scope: ModelScope
    authority: ManifestAuthority
    manifest_digest: Digest

    @model_validator(mode="after")
    def validate_model_scope(self) -> "CapabilityManifest":
        if self.model_scope is ModelScope.independent:
            if self.native_models or self.brokered_models:
                raise ValueError("model-independent capabilities cannot declare model allowlists")
            return self
        if ExecutionMode.native in self.modes and not self.native_models:
            raise ValueError("native model capabilities require an explicit model allowlist")
        if ExecutionMode.brokered in self.modes and not self.brokered_models:
            raise ValueError("brokered model capabilities require an explicit model allowlist")
        return self


class ProbeObservation(VersionedContract):
    succeeded: bool
    code: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
    safe_message: str = Field(min_length=1, max_length=1024)
    evidence_digest: Digest


class CapabilityResult(VersionedContract):
    capability_id: str
    implementation_id: str
    status: CapabilityStatus
    runnable: bool
    requested_model_id: str | None
    effective_model_id: str | None
    mode: ExecutionMode
    manifest_digest: Digest
    model_digest: Digest | None
    runtime_fingerprint: Digest
    hardware_profile_id: Identifier
    hardware_fingerprint: Digest
    evidence: ProbeObservation
    required_permissions: tuple[str, ...] = ()
    reason: str | None = None


class TaskCommand(VersionedContract):
    command_id: CommandId
    task_id: TaskId
    thread_id: ThreadId
    project_id: ProjectId
    command_type: str = Field(min_length=1)
    payload: Mapping[str, JsonValue] = Field(default_factory=dict)

    @field_validator("payload", mode="after")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _validate_json_size(value)
        return _freeze_json(value)

    @field_serializer("payload")
    def serialize_payload(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw_json(value)


class TaskEvent(VersionedContract):
    task_id: TaskId
    sequence: int = Field(ge=0)
    event_type: str = Field(min_length=1)
    payload: Mapping[str, JsonValue] = Field(default_factory=dict)

    @field_validator("payload", mode="after")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _validate_json_size(value)
        return _freeze_json(value)

    @field_serializer("payload")
    def serialize_payload(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw_json(value)


class TaskRecord(VersionedContract):
    task_id: TaskId
    thread_id: ThreadId
    project_id: ProjectId
    status: TaskStatus = TaskStatus.pending
    events: tuple[TaskEvent, ...] = ()


def _freeze_json(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return frozendict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _validate_json_size(value: Mapping[str, JsonValue]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 262_144:
        raise ValueError("payload exceeds 262144 bytes")
