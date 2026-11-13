from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    model: str
    prompt: str


class ChatResult(BaseModel):
    model: str
    status: str
    summary: str
    content: str
    error: Optional[str] = None


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


class SessionRecord(BaseModel):
    schema_version: int = 1
    id: str
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessage] = Field(default_factory=list)
    attachments: List[AttachmentRecord] = Field(default_factory=list)
