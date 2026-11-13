from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


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


class ClipboardTextRequest(BaseModel):
    text: str


class AttachmentUpdate(BaseModel):
    included: bool


class TerminalCreateRequest(BaseModel):
    shell: Literal["powershell", "cmd"] = "powershell"
    cwd: Optional[str] = None
