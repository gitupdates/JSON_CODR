from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_serializer, field_validator, model_validator

from web_app.core.canonical import canonical_digest as compute_canonical_digest


class frozendict(dict):
    """Small immutable mapping used by frozen contract payloads."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("frozendict is immutable")

    __delitem__ = _immutable
    __ior__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


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
    cancel_requested = "cancel_requested"


class EffectState(str, Enum):
    pending = "pending"
    leased = "leased"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancel_requested = "cancel_requested"
    cancelled = "cancelled"
    unknown_requires_reconciliation = "unknown_requires_reconciliation"


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


class CriterionKind(str, Enum):
    command_succeeds = "command_succeeds"
    artifact_exists = "artifact_exists"
    project_state = "project_state"
    user_acceptance = "user_acceptance"


class CriterionStatus(str, Enum):
    pending = "pending"
    passed = "passed"
    failed = "failed"
    blocked = "blocked"


class TaskPhase(str, Enum):
    describe = "describe"
    planning = "planning"
    plan_review = "plan_review"
    executing = "executing"
    verifying = "verifying"
    delivering = "delivering"
    completed = "completed"
    blocked = "blocked"
    failed = "failed"
    cancelled = "cancelled"


class PlanReviewStatus(str, Enum):
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"
    executed = "executed"


class StepReviewStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class StepDisposition(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    interrupted = "interrupted"


class RevisionAuthor(str, Enum):
    planner = "planner"
    user = "user"
    system = "system"


class EffectClass(str, Enum):
    observe = "observe"
    bounded_edit = "bounded_edit"
    test = "test"
    command = "command"
    network = "network"
    install = "install"
    git_local = "git_local"
    publish = "publish"
    external_effect = "external_effect"
    credential_use = "credential_use"
    budget_override = "budget_override"
    destructive = "destructive"


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
    model_digests: Mapping[str, Digest]


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


class CompletionCriterion(VersionedContract):
    criterion_id: Identifier
    kind: CriterionKind
    description: str = Field(min_length=1, max_length=2048)
    parameters: Mapping[str, JsonValue] = Field(default_factory=dict)

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _validate_json_size(value)
        return _freeze_json(value)

    @field_serializer("parameters")
    def serialize_parameters(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw_json(value)


class GoalSpec(VersionedContract):
    goal_id: Identifier
    revision: int = Field(ge=1)
    objective: str = Field(min_length=1, max_length=8192)
    criteria: tuple[CompletionCriterion, ...] = Field(min_length=1)
    accepted: bool = False

    @model_validator(mode="after")
    def unique_criteria(self) -> "GoalSpec":
        identifiers = [item.criterion_id for item in self.criteria]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("criterion identifiers must be unique")
        return self


class OriginReference(FrozenContract):
    origin_type: Literal["skill", "skillset", "plugin", "command", "agent_profile"]
    origin_id: Identifier
    content_digest: Digest


class ConnectorStepMetadata(FrozenContract):
    server_id: Identifier
    tool_name: Identifier
    tool_schema_digest: Digest
    argument_digest: Digest
    declared_annotations: Mapping[str, JsonValue] = Field(default_factory=dict)
    credential_reference: Identifier | None = None
    requested_scope_refs: tuple[str, ...] = ()
    data_origin: str = Field(default="", max_length=2048)

    @field_validator("declared_annotations", mode="after")
    @classmethod
    def freeze_annotations(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _validate_json_size(value)
        return _freeze_json(value)

    @field_serializer("declared_annotations")
    def serialize_annotations(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw_json(value)


class PlannedStep(VersionedContract):
    step_id: Identifier
    plan_id: Identifier
    plan_revision: int = Field(ge=1)
    criterion_ids: tuple[Identifier, ...] = Field(min_length=1)
    title: str = Field(default="", max_length=512)
    purpose: str = Field(default="", max_length=2048)
    dependencies: tuple[Identifier, ...] = ()
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
    operation: str = Field(min_length=1, max_length=256)
    target_path: str | None = Field(default=None, max_length=4096)
    arguments: Mapping[str, JsonValue] = Field(default_factory=dict)
    effect_class: EffectClass = EffectClass.observe
    expected_evidence: tuple[str, ...] = ()
    origins: tuple[OriginReference, ...] = ()
    connector: ConnectorStepMetadata | None = None
    review_status: StepReviewStatus = StepReviewStatus.pending
    disposition: StepDisposition = StepDisposition.pending
    canonical_digest: Digest | None = None

    @field_validator("arguments", mode="after")
    @classmethod
    def freeze_arguments(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _validate_json_size(value)
        return _freeze_json(value)

    @field_serializer("arguments")
    def serialize_arguments(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw_json(value)

    @model_validator(mode="after")
    def set_or_validate_digest(self) -> "PlannedStep":
        expected = compute_canonical_digest(self.model_dump(
            mode="json", exclude={"canonical_digest", "review_status", "disposition", "plan_revision"},
        ))
        if self.canonical_digest is not None and self.canonical_digest != expected:
            raise ValueError("planned step canonical digest does not match its content")
        object.__setattr__(self, "canonical_digest", expected)
        return self


class PlanRevision(VersionedContract):
    plan_id: Identifier
    revision: int = Field(ge=1)
    goal_id: Identifier
    goal_revision: int = Field(ge=1)
    summary: str = Field(default="", max_length=8192)
    expected_deliverables: tuple[str, ...] = ()
    author: RevisionAuthor = RevisionAuthor.planner
    parent_revision: int | None = Field(default=None, ge=1)
    revision_reason: str = Field(default="", max_length=2048)
    review_status: PlanReviewStatus = PlanReviewStatus.draft
    steps: tuple[PlannedStep, ...] = ()
    canonical_digest: Digest | None = None

    @model_validator(mode="after")
    def consistent_steps(self) -> "PlanRevision":
        identifiers = [item.step_id for item in self.steps]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("step identifiers must be unique")
        if any(item.plan_id != self.plan_id or item.plan_revision != self.revision for item in self.steps):
            raise ValueError("steps must belong to this plan revision")
        known = set(identifiers)
        for step in self.steps:
            missing = set(step.dependencies) - known
            if missing:
                raise ValueError(f"step {step.step_id} depends on missing step {sorted(missing)[0]}")
            if step.step_id in step.dependencies:
                raise ValueError("plan dependency cycle detected")
        graph = {step.step_id: step.dependencies for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan dependency cycle detected")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in graph[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in graph:
            visit(step_id)
        digest_payload = self.model_dump(mode="json", exclude={"canonical_digest", "review_status", "steps"})
        digest_payload["steps"] = [
            step.model_dump(mode="json", exclude={"canonical_digest", "review_status", "disposition"})
            for step in self.steps
        ]
        expected = compute_canonical_digest(digest_payload)
        if self.canonical_digest is not None and self.canonical_digest != expected:
            raise ValueError("plan revision canonical digest does not match its content")
        object.__setattr__(self, "canonical_digest", expected)
        return self


class PlanReviewDecision(VersionedContract):
    decision_id: Identifier
    task_id: TaskId
    plan_id: Identifier
    plan_revision: int = Field(ge=1)
    step_id: Identifier | None = None
    plan_digest: Digest
    principal: Identifier
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=4096)
    decided_at: datetime


class EvidenceRef(VersionedContract):
    evidence_id: Identifier
    task_id: TaskId
    project_id: ProjectId
    goal_id: Identifier
    goal_revision: int = Field(ge=1)
    criterion_id: Identifier
    source_ref: str = Field(min_length=1, max_length=2048)
    project_fingerprint: Digest
    observed_at: datetime


class VerificationReport(VersionedContract):
    report_id: Identifier
    task_id: TaskId
    project_id: ProjectId
    goal_id: Identifier
    goal_revision: int = Field(ge=1)
    expected_criterion_ids: tuple[Identifier, ...] = Field(min_length=1)
    results: Mapping[Identifier, CriterionStatus]
    evidence: tuple[EvidenceRef, ...] = ()
    verified_at: datetime

    @field_validator("results", mode="after")
    @classmethod
    def freeze_results(cls, value: Mapping[Identifier, CriterionStatus]) -> Mapping[Identifier, CriterionStatus]:
        return frozendict(value)

    @field_serializer("results")
    def serialize_results(self, value: Mapping[Identifier, CriterionStatus]) -> dict[str, str]:
        return {key: status.value for key, status in value.items()}

    @model_validator(mode="after")
    def complete_result_set(self) -> "VerificationReport":
        if set(self.results) != set(self.expected_criterion_ids):
            raise ValueError("verification results must exactly match expected criteria")
        evidence_by_criterion = {item.criterion_id for item in self.evidence}
        passed = {criterion_id for criterion_id, status in self.results.items() if status is CriterionStatus.passed}
        if not passed.issubset(evidence_by_criterion):
            raise ValueError("passing verification results require criterion evidence")
        if any(
            item.task_id != self.task_id
            or item.project_id != self.project_id
            or item.goal_id != self.goal_id
            or item.goal_revision != self.goal_revision
            or item.criterion_id not in self.results
            for item in self.evidence
        ):
            raise ValueError("verification evidence does not belong to this report")
        return self

    @property
    def satisfied(self) -> bool:
        return bool(self.results) and all(status is CriterionStatus.passed for status in self.results.values())


class TaskCommand(VersionedContract):
    command_id: CommandId
    task_id: TaskId
    thread_id: ThreadId
    project_id: ProjectId
    parent_task_id: TaskId | None = None
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


class _TaskEventContent(VersionedContract):
    event_type: str = Field(min_length=1)
    payload: Mapping[str, JsonValue] = Field(default_factory=dict)
    causation_id: Identifier | None = None

    @field_validator("payload", mode="after")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _validate_json_size(value)
        return _freeze_json(value)

    @field_serializer("payload")
    def serialize_payload(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw_json(value)


class TaskEventDraft(_TaskEventContent):
    pass


class TaskEvent(_TaskEventContent):
    event_id: UUID
    task_id: TaskId
    sequence: int = Field(ge=0)
    global_sequence: int = Field(ge=0)
    source: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    occurred_at: datetime
    previous_event_digest: Digest | None = None
    event_digest: Digest


class _EffectIntentContent(VersionedContract):
    effect_id: Identifier
    capability_id: Identifier
    operation: Identifier
    payload: Mapping[str, JsonValue] = Field(default_factory=dict)
    principal: Identifier
    project_root: str = Field(min_length=1, max_length=4096)
    effect_class: Identifier
    approval_required: bool
    retry_classification: Literal["never", "safe", "reconcile_before_retry"]
    reconciler_id: Identifier
    correlation_id: Identifier
    causation_id: Identifier

    @field_validator("payload", mode="after")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        _validate_json_size(value)
        return _freeze_json(value)

    @field_serializer("payload")
    def serialize_payload(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return _thaw_json(value)


class EffectIntentDraft(_EffectIntentContent):
    pass


class EffectIntent(_EffectIntentContent):
    task_id: TaskId
    state: EffectState
    attempt_count: int = Field(ge=0)
    lease_owner: Identifier | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TaskRecord(VersionedContract):
    task_id: TaskId
    thread_id: ThreadId
    project_id: ProjectId
    parent_task_id: TaskId | None = None
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
