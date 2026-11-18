from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from web_app.version import APP_VERSION


class ChatRequest(BaseModel):
    model: str
    prompt: str
    session_id: Optional[str] = None


class HardwareProbeRequest(BaseModel):
    backend: Literal["cpu", "ollama_gpu", "cuda_v12", "cuda_v13", "rocm_v7_1", "vulkan"]
    model: str = Field(min_length=1, max_length=200)


class HardwareBenchmarkRequest(BaseModel):
    suite: Literal["quick", "thorough"] = "quick"
    model: str = Field(min_length=1, max_length=200)
    backend: str = Field(default="all", min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$")


class IntegrityBenchmarkRequest(BaseModel):
    suite: Literal["quick", "thorough"] = "quick"
    model: str = Field(min_length=1, max_length=200)


class ActionSuggestion(BaseModel):
    command: str = Field(min_length=1, max_length=2000)
    cwd: Optional[str] = Field(default=None, max_length=500)
    explanation: str = Field(min_length=1, max_length=1000)

    @field_validator("command", "cwd", "explanation")
    @classmethod
    def reject_control_characters(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Control characters are not allowed")
        return value


class CodingAgentSuggestion(BaseModel):
    tool: Literal["continue", "aider"]
    project_root: str = Field(min_length=1, max_length=1000)
    prompt: str = Field(min_length=1, max_length=20_000)


class BrokerAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["status", "read", "apply_patch", "verify", "commit", "sync", "push"]
    paths: List[str] = Field(default_factory=list, max_length=100)
    patch: Optional[str] = Field(default=None, max_length=200_000)
    message: Optional[str] = Field(default=None, max_length=500)
    checks: List[str] = Field(default_factory=list, max_length=20)

    @field_validator("paths")
    @classmethod
    def paths_stay_relative(cls, values: List[str]) -> List[str]:
        for value in values:
            path = value.replace("\\", "/")
            if not path or path.startswith("/") or ":" in path or ".." in path.split("/"):
                raise ValueError("Broker paths must stay inside the project")
        return values


class BrokerActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    project_root: str = Field(min_length=1, max_length=1000)
    actions: List[BrokerAction] = Field(min_length=1, max_length=50)
    baseline_fingerprint: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_workflow(self):
        if sum(len(action.patch or "") for action in self.actions) > 250_000:
            raise ValueError("aggregate patch payload is too large")
        kinds = [action.kind for action in self.actions]
        if "push" in kinds and kinds[-1] != "push":
            raise ValueError("push must be the final action")
        if "commit" in kinds:
            commit_index = kinds.index("commit")
            if "apply_patch" not in kinds[:commit_index]:
                raise ValueError("commit requires a preceding apply_patch action")
        if "push" in kinds and "commit" not in kinds[:kinds.index("push")]:
            raise ValueError("push requires a preceding commit action")
        return self


class ActionProposal(BaseModel):
    id: str
    session_id: str
    command: str
    cwd: str
    explanation: str
    source_skill_ids: List[str] = Field(default_factory=list)
    risk: Literal["normal", "destructive"]
    risk_reason: str
    status: Literal["pending", "awaiting_confirmation", "approved", "rejected", "superseded", "consumed"] = "pending"
    confirmation_phrase: Optional[str] = None


class ActionApprovalResult(BaseModel):
    proposal_id: str
    requires_confirmation: bool = False
    confirmation_phrase: Optional[str] = None
    token: Optional[str] = None
    expires_in: Optional[int] = None


class ApprovedAction(BaseModel):
    proposal_id: str
    command: str
    cwd: str


class ActionApprovalRequest(BaseModel):
    terminal_id: str = Field(min_length=1, max_length=64)


class DestructiveConfirmationRequest(ActionApprovalRequest):
    phrase: str = Field(min_length=1, max_length=200)


class ChatResult(BaseModel):
    model: str
    status: str
    summary: str
    content: str
    error: Optional[str] = None
    artifact: Optional["ArtifactRecord"] = None
    attached_skills: List["AttachedSkill"] = Field(default_factory=list)
    attached_skillsets: List[str] = Field(default_factory=list)
    skill_recommendations: List["SkillRecommendation"] = Field(default_factory=list)
    actions: List[ActionSuggestion] = Field(default_factory=list)
    coding_agent_tasks: List[CodingAgentSuggestion] = Field(default_factory=list)
    action_proposals: List[ActionProposal] = Field(default_factory=list)
    reasoning: Optional["ReasoningTrace"] = None
    references: List["ObjectReference"] = Field(default_factory=list)
    run_id: Optional[str] = Field(default=None, max_length=128)
    provider_events: List[Dict[str, object]] = Field(default_factory=list, exclude=True)


class GeneratedFile(BaseModel):
    path: str
    content: str


class ConversionBundle(BaseModel):
    summary: str
    files: List[GeneratedFile] = Field(default_factory=list)


class ArtifactRecord(BaseModel):
    filename: str
    path: str
    url: Optional[str] = None


class ModelInfo(BaseModel):
    name: str
    installed: bool
    size: Optional[int] = None
    quantization: Optional[str] = None
    context_length: Optional[int] = None
    capabilities: List[str] = Field(default_factory=list)


class ExtractionState(str, Enum):
    pending = "pending"
    ready = "ready"
    rejected = "rejected"
    failed = "failed"


class ReasoningEntry(BaseModel):
    sequence: int = Field(ge=0)
    kind: Literal["assumption", "plan", "analysis", "evidence", "uncertainty", "verification", "conclusion"]
    text: str = Field(min_length=1, max_length=100_000)
    provenance: Literal["native_provider", "provider_tag", "public_rationale"]
    reference_ids: List[str] = Field(default_factory=list, max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReasoningTrace(BaseModel):
    schema_version: Literal[1] = 1
    entries: List[ReasoningEntry] = Field(default_factory=list, max_length=10_000)
    warnings: List[str] = Field(default_factory=list, max_length=100)


class ObjectReference(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    kind: Literal["attachment", "artifact", "project_file", "url", "skill", "task", "command"]
    label: str = Field(min_length=1, max_length=500)
    target: str = Field(min_length=1, max_length=2000)
    preview_url: Optional[str] = Field(default=None, max_length=2000)
    download_url: Optional[str] = Field(default=None, max_length=2000)
    available: bool = True


class CanonicalContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1


class ModelRunCreateRequest(CanonicalContract):
    session_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=200_000)
    attachment_ids: List[str] = Field(default_factory=list, max_length=1000)
    profile: Literal["general", "code_jury"] = "general"
    parallelism: int = Field(default=2, ge=1, le=4)
    public_reasoning: bool = False
    request_key: Optional[str] = Field(default=None, min_length=1, max_length=128)


class ModelTiming(CanonicalContract):
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: int = Field(ge=0)


class ModelInputManifest(CanonicalContract):
    prompt_included: bool = True
    attachment_ids: List[str] = Field(default_factory=list, max_length=1000)
    text_sources: List[str] = Field(default_factory=list, max_length=1000)
    image_sources: List[str] = Field(default_factory=list, max_length=1000)
    omitted_modalities: List[str] = Field(default_factory=list, max_length=100)
    adaptations: List[str] = Field(default_factory=list, max_length=100)


class OriginalModelOutput(CanonicalContract):
    output_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=10_000_000)
    reasoning_entries: List[ReasoningEntry] = Field(default_factory=list, max_length=10_000)
    provider_events: List[Dict[str, object]] = Field(default_factory=list, max_length=100_000)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResponseConsistency(CanonicalContract):
    required_labels: List[str] = Field(default_factory=list, max_length=100)
    present_labels: List[str] = Field(default_factory=list, max_length=100)
    missing_labels: List[str] = Field(default_factory=list, max_length=100)
    format_compliant: bool = True
    answer_matches_original: bool = True


class CanonicalModelResult(CanonicalContract):
    result_id: str = Field(min_length=1, max_length=128)
    requested_model: str = Field(min_length=1, max_length=500)
    effective_model: str = Field(min_length=1, max_length=500)
    status: Literal["queued", "running", "completed", "timeout", "failed", "cancelled", "unsupported"]
    timing: ModelTiming
    input_manifest: ModelInputManifest = Field(default_factory=ModelInputManifest)
    original_output_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    original_output_digest: Optional[str] = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    summary: str = Field(default="", max_length=1000)
    answer: str = Field(default="", max_length=10_000_000)
    reasoning: Optional[ReasoningTrace] = None
    evidence: List[ObjectReference] = Field(default_factory=list, max_length=1000)
    warnings: List[str] = Field(default_factory=list, max_length=1000)
    references: List[ObjectReference] = Field(default_factory=list, max_length=1000)
    actions: List[ActionSuggestion] = Field(default_factory=list, max_length=1000)
    consistency: ResponseConsistency = Field(default_factory=ResponseConsistency)
    normalizer_version: Literal[1] = 1
    error_code: Optional[str] = Field(default=None, max_length=128)
    error_message: Optional[str] = Field(default=None, max_length=2000)


class JurorVerdict(CanonicalContract):
    model: str = Field(min_length=1, max_length=500)
    score: int = Field(ge=1, le=10)
    critical_issues: List[str] = Field(default_factory=list, max_length=1000)
    rationale: str = Field(min_length=1, max_length=100_000)
    original_output_id: str = Field(min_length=1, max_length=128)


class ConsensusVerdict(CanonicalContract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    consensus_score: float = Field(ge=1.0, le=10.0)
    verdict: Literal["PASS", "CONDITIONAL_PASS", "FAIL"]
    agreed_issues: List[str] = Field(default_factory=list, max_length=1000)
    dissenting_notes: List[str] = Field(default_factory=list, max_length=1000)
    synthesis_rationale: str = Field(min_length=1, max_length=100_000)
    synthesizer_model: str = Field(min_length=1, max_length=500)
    included_jurors: tuple[str, ...] = ()
    excluded_jurors: tuple[str, ...] = ()


class CanonicalModelRun(CanonicalContract):
    run_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    mode: Literal["batch", "single"]
    profile: Literal["general", "code_jury"] = "general"
    parallelism: int = Field(default=2, ge=1, le=4)
    status: Literal["queued", "running", "completed", "partial", "failed", "cancelled"]
    prompt: str = Field(min_length=1, max_length=200_000)
    roster: List[str] = Field(default_factory=list, max_length=1000)
    unavailable_models: List[str] = Field(default_factory=list, max_length=1000)
    results: List[CanonicalModelResult] = Field(default_factory=list, max_length=1000)
    consensus: Optional[ConsensusVerdict] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class MessageArtifact(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    filename: str = Field(min_length=1, max_length=500)
    media_type: str = Field(min_length=1, max_length=200)
    size: int = Field(ge=0)
    download_url: str = Field(min_length=1, max_length=2000)


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[0-9a-f]{32}$")
    role: Literal["user", "assistant", "system"]
    content: str
    status: Literal["pending", "streaming", "completed", "incomplete", "failed"] = "completed"
    task_id: Optional[str] = Field(default=None, max_length=128)
    requested_model: Optional[str] = Field(default=None, max_length=500)
    effective_model: Optional[str] = Field(default=None, max_length=500)
    reasoning: Optional[ReasoningTrace] = None
    references: List[ObjectReference] = Field(default_factory=list, max_length=1000)
    attachment_ids: List[str] = Field(default_factory=list, max_length=1000)
    artifacts: List[MessageArtifact] = Field(default_factory=list, max_length=1000)
    parent_message_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AttachmentRecord(BaseModel):
    id: str
    display_name: str
    detected_type: Optional[str] = None
    size: int = 0
    digest: Optional[str] = None
    extraction_state: ExtractionState = ExtractionState.pending
    included: bool = True
    warnings: List[str] = Field(default_factory=list)
    storage_name: Optional[str] = None
    extracted_name: Optional[str] = None


class SessionRecord(BaseModel):
    schema_version: int = 2
    id: str
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessage] = Field(default_factory=list)
    attachments: List[AttachmentRecord] = Field(default_factory=list)
    selected_skill_ids: List[str] = Field(default_factory=list)
    auto_attach_skills: bool = True
    excluded_skill_ids: List[str] = Field(default_factory=list)

    @field_validator("excluded_skill_ids")
    @classmethod
    def deduplicate_exclusions(cls, value: List[str]) -> List[str]:
        return list(dict.fromkeys(value))


class ClipboardTextRequest(BaseModel):
    text: str


class AttachmentUpdate(BaseModel):
    included: bool


class TerminalCreateRequest(BaseModel):
    shell: Literal["powershell", "cmd"] = "powershell"
    cwd: Optional[str] = None


class CodingAgentGrantRequest(BaseModel):
    project_root: str = Field(min_length=1, max_length=1000)
    tool: Literal["broker", "shell", "continue", "aider"]


class BrokerGrantRequest(BaseModel):
    project_root: str = Field(min_length=1, max_length=1000)
    profile: Literal["broker", "shell", "continue", "aider"] = "broker"


class BrokerTaskRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    grant_id: str = Field(min_length=1, max_length=64)
    request: BrokerActionRequest


class BrokerAdapterRunRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    grant_id: str = Field(min_length=1, max_length=64)
    project_root: str = Field(min_length=1, max_length=1000)
    prompt: str = Field(min_length=1, max_length=20_000)


class ProjectWorkspaceRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_root: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=200)
    outcome: str = Field(min_length=1, max_length=20_000)


class WorkspaceTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_root: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(min_length=1, max_length=128)
    engine_id: str = Field(min_length=1, max_length=200)
    model_selection: str = Field(min_length=1, max_length=500)
    prompt: str = Field(min_length=1, max_length=200_000)
    context_references: List[str] = Field(default_factory=list, max_length=1000)


class WorkspaceTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=128)
    requested_engine: str
    effective_engine: str
    requested_model: str
    effective_model: Optional[str] = None
    route: str
    status: str
    warnings: List[str] = Field(default_factory=list)
    result: Optional[Dict[str, object]] = None
    artifact_references: List[ObjectReference] = Field(default_factory=list)


class TaskDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    executed_plan_id: Optional[str] = None
    executed_plan_revision: Optional[int] = None
    executed_plan_digest: Optional[str] = None
    route_disclosure: Dict[str, object] = Field(default_factory=dict)
    changed_paths: tuple[str, ...] = ()
    child_results: tuple[Dict[str, object], ...] = ()
    verification: Dict[str, object] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    recovery_controls: Dict[str, bool] = Field(default_factory=dict)
    artifacts: tuple[Dict[str, object], ...] = ()


class CodingAgentLaunchRequest(CodingAgentGrantRequest):
    model: str = Field(min_length=1, max_length=200)
    mode: Literal["interactive", "delegated"] = "interactive"
    prompt: Optional[str] = Field(default=None, max_length=20_000)


class SkillRecord(BaseModel):
    id: str
    name: str
    description: str = ""
    content: str
    original_content: str = ""
    enabled: bool = True


class SkillPack(BaseModel):
    id: str
    name: str
    source_format: Literal["claude", "codex", "generic"]
    source_name: str
    source_path: Optional[str] = None
    source_digest: Optional[str] = None
    skills: List[SkillRecord] = Field(default_factory=list)


class SkillsetMember(BaseModel):
    reference: str
    name: str


class SkillsetRecord(BaseModel):
    id: str
    name: str
    category: str
    members: List[SkillsetMember] = Field(default_factory=list)
    routing_terms: List[str] = Field(default_factory=list)
    attachment_extensions: List[str] = Field(default_factory=list)
    summary: str = ""
    enabled: bool = True
    auto_attach: bool = True
    version: int = 1


class SkillRecommendation(BaseModel):
    reference: str
    name: str
    score: int
    reasons: List[str] = Field(default_factory=list)
    skillset_ids: List[str] = Field(default_factory=list)
    manual: bool = False


class SkillRecommendationResult(BaseModel):
    recommendations: List[SkillRecommendation] = Field(default_factory=list)
    skillset_ids: List[str] = Field(default_factory=list)


class AttachedSkill(BaseModel):
    reference: str
    name: str
    score: int = 0
    reasons: List[str] = Field(default_factory=list)
    manual: bool = False


class ContextBuildResult(BaseModel):
    prompt: str
    attached_skills: List[AttachedSkill] = Field(default_factory=list)
    skillsets: List[str] = Field(default_factory=list)
    omitted: List[str] = Field(default_factory=list)


class SkillRecommendationRequest(BaseModel):
    prompt: str = Field(min_length=1)


class SessionSkillRoutingUpdate(BaseModel):
    auto_attach_skills: Optional[bool] = None
    excluded_skill_ids: Optional[List[str]] = None


class SkillUpdateRequest(BaseModel):
    content: str
    enabled: bool = True
    session_id: Optional[str] = None


class SkillPackRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SkillSelectionRequest(BaseModel):
    selected: List[str] = Field(default_factory=list)


class UiSettings(BaseModel):
    skill_catalog_open: bool = True
    theme: Literal["light", "dark", "system"] = "dark"
    sidebar_collapsed: bool = False
    sidebar_width: int = 260
    primary_destination: Literal["workspace", "chat", "terminal", "context", "skills", "hardware", "settings"] = "workspace"
    hardware_section: Literal[
        "overview", "profiles", "runtimes", "compatibility", "model-search", "benchmarks", "leaderboard", "history", "localperf"
    ] = "overview"

    @field_validator("sidebar_width", mode="before")
    @classmethod
    def bound_sidebar_width(cls, value: object) -> int:
        width = int(value)
        return min(380, max(220, width))


class UiSettingsUpdate(BaseModel):
    skill_catalog_open: Optional[bool] = None
    theme: Optional[Literal["light", "dark", "system"]] = None
    sidebar_collapsed: Optional[bool] = None
    sidebar_width: Optional[int] = None
    primary_destination: Optional[Literal["workspace", "chat", "terminal", "context", "skills", "hardware", "settings"]] = None
    hardware_section: Optional[Literal[
        "overview", "profiles", "runtimes", "compatibility", "model-search", "benchmarks", "leaderboard", "history", "localperf"
    ]] = None

    @field_validator("sidebar_width", mode="before")
    @classmethod
    def bound_sidebar_width(cls, value: object) -> Optional[int]:
        if value is None:
            return None
        width = int(value)
        return min(380, max(220, width))

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "UiSettingsUpdate":
        for field in (
            "skill_catalog_open", "theme", "sidebar_collapsed", "sidebar_width",
            "primary_destination", "hardware_section",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self



class SkillScanSettings(BaseModel):
    approved_directories: List[str] = Field(default_factory=list)


class SkillRoutingSettings(BaseModel):
    auto_attach: bool = True
    max_skillsets: int = Field(default=3, ge=1, le=10)
    max_skills: int = Field(default=5, ge=1, le=20)
    minimum_score: int = Field(default=8, ge=1, le=100)


class GpuProfileSettings(BaseModel):
    mode: Literal[
        "automatic", "gpu_preferred", "balanced", "vram_conservative", "cpu_only", "advanced"
    ] = "automatic"
    num_gpu: Optional[int] = Field(default=None, ge=0, le=999)
    main_gpu: Optional[int] = Field(default=None, ge=0, le=15)
    num_ctx: Optional[int] = Field(default=None, ge=512, le=131072)
    num_batch: Optional[int] = Field(default=None, ge=1, le=2048)

    @model_validator(mode="after")
    def validate_advanced_profile(self) -> "GpuProfileSettings":
        manual = (self.num_gpu, self.main_gpu, self.num_ctx, self.num_batch)
        if self.mode == "advanced" and all(value is None for value in manual):
            raise ValueError("Advanced profile requires at least one manual option")
        if self.mode != "advanced" and any(value is not None for value in manual):
            raise ValueError("Manual options require the advanced profile")
        return self

    def ollama_options(self) -> dict:
        presets = {
            "automatic": {},
            "gpu_preferred": {"num_gpu": 999},
            "balanced": {"num_gpu": 16},
            "vram_conservative": {"num_ctx": 2048, "num_batch": 128},
            "cpu_only": {"num_gpu": 0},
        }
        if self.mode != "advanced":
            return presets[self.mode]
        return {
            name: value for name, value in (
                ("num_gpu", self.num_gpu),
                ("main_gpu", self.main_gpu),
                ("num_ctx", self.num_ctx),
                ("num_batch", self.num_batch),
            ) if value is not None
        }


class GpuOptimizationSettings(BaseModel):
    default_profile: GpuProfileSettings = Field(default_factory=GpuProfileSettings)
    model_profiles: Dict[str, GpuProfileSettings] = Field(default_factory=dict)


PolicyOverride = Literal["allow", "ask", "deny"]


class ExecutionPolicySettings(BaseModel):
    preset: Literal["balanced", "strict", "autonomous"] = "balanced"
    global_overrides: Dict[str, PolicyOverride] = Field(default_factory=dict)
    project_overrides: Dict[str, Dict[str, PolicyOverride]] = Field(default_factory=dict)


class SystemSettings(BaseModel):
    version: int = 3
    app_version: str = APP_VERSION
    ui: UiSettings = Field(default_factory=UiSettings)
    skill_scan: SkillScanSettings = Field(default_factory=SkillScanSettings)
    skill_routing: SkillRoutingSettings = Field(default_factory=SkillRoutingSettings)
    gpu_optimization: GpuOptimizationSettings = Field(default_factory=GpuOptimizationSettings)
    execution_policy: ExecutionPolicySettings = Field(default_factory=ExecutionPolicySettings)


class SettingsUpdate(BaseModel):
    ui: Optional[UiSettingsUpdate] = None
    skill_scan: Optional[SkillScanSettings] = None
    skill_routing: Optional[SkillRoutingSettings] = None
    gpu_optimization: Optional[GpuOptimizationSettings] = None
    execution_policy: Optional[ExecutionPolicySettings] = None


class SkillScanRequest(BaseModel):
    directory: str


class KnownSkillScanRequest(BaseModel):
    fallback_token: str


class DiscoveryInstallRequest(BaseModel):
    discovery_id: str


class GithubSkillPreviewRequest(BaseModel):
    url: str


class GithubSkillInstallRequest(BaseModel):
    preview_id: str


class SkillDiscovery(BaseModel):
    id: str
    name: str
    source_format: Literal["claude", "codex", "generic"]
    source_path: str
    skill_count: int
    already_installed: bool = False


class SkillScanResult(BaseModel):
    discoveries: List[SkillDiscovery] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    fallback_token: Optional[str] = None
