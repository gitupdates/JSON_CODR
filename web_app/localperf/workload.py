from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

WORKLOAD_NAME = "LocalPerf-Core-v1"
WORKLOAD_VERSION = "1.0"


@dataclass(frozen=True)
class WorkloadPrompt:
    id: str
    category: str
    prompt: str
    quality_scored: bool = False


CORE_WORKLOAD = (
    WorkloadPrompt("lp-01", "short-factual", "Return only the result of 17 * 23."),
    WorkloadPrompt("lp-02", "short-creative", "Write two sentences about a library during a thunderstorm."),
    WorkloadPrompt("lp-03", "instruction", "Return only this phrase in uppercase: local models are ready"),
    WorkloadPrompt("lp-04", "explanation", "Explain a hash table in at most 80 words."),
    WorkloadPrompt("lp-05", "reasoning", "A service handles 48 requests per second for 125 seconds. Return the total requests and one calculation line."),
    WorkloadPrompt("lp-06", "summarization", "Summarize in one sentence: A local inference service loads a model once, accepts multiple prompts, and keeps all data on the user's machine."),
    WorkloadPrompt("lp-07", "code", "Return only Python defining clamp(value, minimum, maximum).", True),
    WorkloadPrompt("lp-08", "code-repair", "Return only Python defining deduplicate(items) that preserves first-seen order.", True),
    WorkloadPrompt("lp-09", "structured", 'Return only JSON with exactly status="ok" and items=[1,2].', True),
    WorkloadPrompt("lp-10", "sql", "Return one parameterized SQLite SELECT that gets a user's name by id from users(id, name), using ?.", True),
    WorkloadPrompt("lp-11", "long-explanation", "Compare CPU, GPU, and NPU local inference, covering compatibility, memory, throughput, and fallback behavior in 250-400 words."),
    WorkloadPrompt("lp-12", "technical-review", "Review this system statement and return Summary, Risks, and Recommendations: The application selects accelerators after capability probes and retains CPU as its compatibility fallback."),
)


def workload_hash() -> str:
    payload = {"name": WORKLOAD_NAME, "version": WORKLOAD_VERSION, "prompts": [asdict(item) for item in CORE_WORKLOAD]}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
