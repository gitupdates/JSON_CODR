from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import CanonicalModelResult, ConsensusVerdict, JurorVerdict


class JuryValidationError(ValueError):
    def __init__(self, message: str, original_output_id: str | None):
        super().__init__(message)
        self.original_output_id = original_output_id


class _JurorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=1, le=10)
    critical_issues: list[str] = Field(default_factory=list, max_length=1000)
    rationale: str = Field(min_length=1, max_length=100_000)


class _SynthesisPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agreed_issues: list[str] = Field(default_factory=list, max_length=1000)
    dissenting_notes: list[str] = Field(default_factory=list, max_length=1000)
    synthesis_rationale: str = Field(default="Synthesis completed.", min_length=1, max_length=100_000)


def validate_juror_result(result: CanonicalModelResult) -> JurorVerdict:
    try:
        payload = _JurorPayload.model_validate(json.loads(result.answer))
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise JuryValidationError(str(error), result.original_output_id) from error
    if result.original_output_id is None:
        raise JuryValidationError("juror result has no preserved original output", None)
    return JurorVerdict(
        model=result.requested_model,
        score=payload.score,
        critical_issues=payload.critical_issues,
        rationale=payload.rationale,
        original_output_id=result.original_output_id,
    )


def build_consensus(
    verdicts: Iterable[JurorVerdict],
    failures: Iterable[str],
    synthesizers: Iterable[tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]],
) -> ConsensusVerdict:
    jurors = list(verdicts)
    if not jurors:
        raise ValueError("at least one valid juror verdict is required")
    score = round(sum(item.score for item in jurors) / len(jurors), 2)
    critical = any(item.critical_issues for item in jurors)
    verdict = "FAIL" if critical or score < 6 else ("PASS" if score >= 8 else "CONDITIONAL_PASS")
    synthesis = _SynthesisPayload(synthesis_rationale="All synthesizers failed; deterministic consensus retained.")
    synthesizer_model = "unavailable"
    synthesis_input = {
        "consensus_score": score,
        "verdict": verdict,
        "jurors": [item.model_dump(mode="json") for item in jurors],
    }
    for model, synthesizer in synthesizers:
        try:
            synthesis = _SynthesisPayload.model_validate(synthesizer(synthesis_input))
            synthesizer_model = model
            break
        except Exception:
            continue
    return ConsensusVerdict(
        consensus_score=score,
        verdict=verdict,
        agreed_issues=synthesis.agreed_issues,
        dissenting_notes=synthesis.dissenting_notes,
        synthesis_rationale=synthesis.synthesis_rationale,
        synthesizer_model=synthesizer_model,
        included_jurors=tuple(item.model for item in jurors),
        excluded_jurors=tuple(failures),
    )
