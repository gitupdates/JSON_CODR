from __future__ import annotations

import statistics
import uuid
from typing import Iterable

from web_app.localperf.fingerprint import configuration_hash
from web_app.localperf.models import ConfigurationRecord, ConformanceResult, LocalPerfRun, MetricSummary, SampleRecord
from web_app.localperf.workload import CORE_WORKLOAD, WORKLOAD_NAME, WORKLOAD_VERSION, workload_hash


def _summary(values: Iterable[float]) -> MetricSummary:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(.95 * len(ordered) + .999999) - 1))
    return MetricSummary(count=len(ordered), mean=statistics.fmean(ordered), median=statistics.median(ordered),
                         minimum=ordered[0], maximum=ordered[-1], p95=ordered[index])


def aggregate_run(samples: list[SampleRecord], metadata: dict, suite: str, repetitions: int) -> LocalPerfRun:
    config = ConfigurationRecord(hash=configuration_hash(metadata), **metadata)
    expected = {(item.id, repetition) for repetition in range(1, repetitions + 1) for item in CORE_WORKLOAD}
    actual = {(item.prompt_id, item.repetition) for item in samples}
    reasons = []
    if expected != actual:
        reasons.append("incomplete_samples")
    if any(not item.success for item in samples):
        reasons.append("sample_failure")
    scored = [item for item in samples if item.prompt_id in {"lp-07", "lp-08", "lp-09", "lp-10"}]
    if len(scored) != 4 * repetitions or any(item.quality is None for item in scored):
        reasons.append("missing_quality_execution")
    quality_values = [item.quality.passed for item in scored if item.quality and item.quality.passed is not None]
    metrics = {}
    for name in ("generation_tokens_per_second", "ttft_ms", "peak_vram_mb", "total_duration_ms"):
        values = [float(getattr(item, name)) for item in samples]
        if values:
            metrics[name] = _summary(values)
    return LocalPerfRun(
        evaluation_id=str(uuid.uuid4()), workload_name=WORKLOAD_NAME, workload_version=WORKLOAD_VERSION,
        workload_hash=workload_hash(), suite=suite, repetitions=repetitions, configuration=config,
        samples=samples, metrics=metrics, success_rate=sum(item.success for item in samples) / len(samples) if samples else 0,
        quality_rate=sum(value is True for value in quality_values) / len(quality_values) if quality_values else None,
        conformance=ConformanceResult(conforming=not reasons, eligible=not reasons, reasons=reasons),
    )
