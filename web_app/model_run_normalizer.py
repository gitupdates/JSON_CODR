from __future__ import annotations

import hashlib
import json
from typing import Iterable

from web_app.models import (
    CanonicalModelResult,
    ChatResult,
    ModelInputManifest,
    ModelTiming,
    OriginalModelOutput,
    ReasoningEntry,
)


def capture_original_output(
    *,
    output_id: str,
    model: str,
    content: str,
    reasoning_entries: Iterable[ReasoningEntry],
    provider_events: list[dict[str, object]],
) -> OriginalModelOutput:
    entries = list(reasoning_entries)
    digest_payload = {
        "model": model,
        "content": content,
        "reasoning_entries": [entry.model_dump(mode="json") for entry in entries],
        "provider_events": provider_events,
    }
    encoded = json.dumps(
        digest_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return OriginalModelOutput(
        output_id=output_id,
        model=model,
        content=content,
        reasoning_entries=entries,
        provider_events=provider_events,
        digest=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
    )


def normalize_model_result(
    original: OriginalModelOutput,
    result: ChatResult | None,
    *,
    warnings: list[str],
    timing: ModelTiming,
) -> CanonicalModelResult:
    answer = result.content if result is not None else original.content
    summary = result.summary.strip() if result is not None else ""
    if not summary:
        summary = next((line.strip() for line in answer.splitlines() if line.strip()), "")[:240]
    references = list(result.references) if result is not None else []
    normalized_warnings = list(warnings)
    if result is not None and result.error == "structured_output_fallback":
        normalized_warnings.append("Model returned plain text; JSON_CODR normalized the response.")
    return CanonicalModelResult(
        result_id=original.output_id,
        requested_model=original.model,
        effective_model=result.model if result is not None else original.model,
        status="completed" if answer else "failed",
        timing=timing,
        input_manifest=ModelInputManifest(),
        original_output_id=original.output_id,
        original_output_digest=original.digest,
        summary=summary,
        answer=answer,
        reasoning=result.reasoning if result is not None else None,
        evidence=references,
        warnings=normalized_warnings,
        references=references,
        actions=list(result.actions) if result is not None else [],
    )
