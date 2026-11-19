from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

LOCALPERF_SCHEMA_VERSION = "0.3.0-localperf"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfigurationRecord(StrictModel):
    hash: str
    model: str
    backend: str
    profile: str = "automatic"
    hardware: dict[str, Any] = Field(default_factory=dict)
    software: dict[str, Any] = Field(default_factory=dict)


class QualityResult(StrictModel):
    passed: bool | None
    score: float | None = None
    reason: str


class SampleRecord(StrictModel):
    prompt_id: str
    repetition: int = Field(ge=1)
    success: bool
    generation_tokens_per_second: float = Field(gt=0)
    ttft_ms: float = Field(ge=0)
    peak_vram_mb: float = Field(ge=0)
    total_duration_ms: float = Field(gt=0)
    prompt_tokens: int = Field(ge=0)
    generated_tokens: int = Field(gt=0)
    output: str = ""
    error: str | None = None
    quality: QualityResult | None = None


class MetricSummary(StrictModel):
    count: int
    mean: float
    median: float
    minimum: float
    maximum: float
    p95: float


class ConformanceResult(StrictModel):
    conforming: bool
    eligible: bool
    reasons: list[str] = Field(default_factory=list)


class LocalPerfRun(StrictModel):
    schema_version: str = LOCALPERF_SCHEMA_VERSION
    evaluation_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    workload_name: str
    workload_version: str
    workload_hash: str
    suite: str
    repetitions: int
    configuration: ConfigurationRecord
    samples: list[SampleRecord]
    metrics: dict[str, MetricSummary]
    success_rate: float
    quality_rate: float | None
    conformance: ConformanceResult
