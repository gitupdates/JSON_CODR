from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ChatRequest(BaseModel):
    model: str
    prompt: str
    session_id: Optional[str] = None


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


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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


class UiSettingsUpdate(BaseModel):
    skill_catalog_open: Optional[bool] = None
    theme: Optional[Literal["light", "dark", "system"]] = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "UiSettingsUpdate":
        for field in ("skill_catalog_open", "theme"):
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


class SystemSettings(BaseModel):
    version: int = 2
    ui: UiSettings = Field(default_factory=UiSettings)
    skill_scan: SkillScanSettings = Field(default_factory=SkillScanSettings)
    skill_routing: SkillRoutingSettings = Field(default_factory=SkillRoutingSettings)


class SettingsUpdate(BaseModel):
    ui: Optional[UiSettingsUpdate] = None
    skill_scan: Optional[SkillScanSettings] = None
    skill_routing: Optional[SkillRoutingSettings] = None


class SkillScanRequest(BaseModel):
    directory: str


class KnownSkillScanRequest(BaseModel):
    fallback_token: str


class DiscoveryInstallRequest(BaseModel):
    discovery_id: str


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
