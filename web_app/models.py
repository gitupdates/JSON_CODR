from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


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
    schema_version: int = 1
    id: str
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessage] = Field(default_factory=list)
    attachments: List[AttachmentRecord] = Field(default_factory=list)
    selected_skill_ids: List[str] = Field(default_factory=list)


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


class SystemSettings(BaseModel):
    version: int = 1
    ui: UiSettings = Field(default_factory=UiSettings)
    skill_scan: SkillScanSettings = Field(default_factory=SkillScanSettings)


class SettingsUpdate(BaseModel):
    ui: Optional[UiSettingsUpdate] = None
    skill_scan: Optional[SkillScanSettings] = None


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
