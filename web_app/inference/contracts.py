from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from web_app.models import ChatResult
from web_app.inference.protocol import (
    CancellationMetadata,
    ContentPart,
    InferenceEvent,
    InferenceFinishReason,
    InferenceMessage,
    InferenceRequest,
    InferenceUsage,
    ResponseFormat,
    ToolDefinition,
)

__all__ = [
    "CancellationMetadata",
    "ContentPart",
    "InferenceEvent",
    "InferenceFinishReason",
    "InferenceMessage",
    "InferenceRequest",
    "InferenceUsage",
    "ResponseFormat",
    "ToolDefinition",
    "ProviderKind",
    "ProviderState",
    "OptimizedArtifactRecord",
    "OptimizedModelRecord",
    "ProbeResult",
    "InferenceProvider",
]


class ProviderKind(str, Enum):
    ollama = "ollama"
    openvino = "openvino"
    ryzen_ai = "ryzen_ai"
    winml = "winml"
    directml = "directml"


class ProviderState(BaseModel):
    provider: ProviderKind
    name: str
    kind: str
    hardware_detected: bool = False
    runtime_ready: bool = False
    model_ready: bool = False
    verified: bool = False
    evidence: list[str] = Field(default_factory=list)
    reason: str | None = None


class OptimizedArtifactRecord(BaseModel, frozen=True):
    path: str
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OptimizedModelRecord(BaseModel, frozen=True):
    id: str
    provider: ProviderKind
    repository: str
    source_url: str
    revision: str
    license: str
    device: str
    format: str
    requirements: tuple[str, ...]
    ollama_fallback: str | None = None
    context_length: int | None = None
    maximum_download_bytes: int | None = Field(default=None, gt=0)
    artifacts: tuple[OptimizedArtifactRecord, ...] = ()


class ProbeResult(BaseModel):
    model_id: str
    provider: ProviderKind
    success: bool
    response: ChatResult | None = None
    error: str | None = None


class InferenceProvider(Protocol):
    async def health(self) -> dict[str, Any]: ...

    async def list_models(self) -> list[OptimizedModelRecord]: ...

    async def probe(self, model: OptimizedModelRecord) -> ProbeResult: ...

    async def chat(self, model: OptimizedModelRecord, prompt: str, images: list[Any] | None = None) -> ChatResult: ...

    async def benchmark(
        self, model: OptimizedModelRecord, prompts: list[str], repeats: int
    ) -> list[dict[str, Any]]: ...
