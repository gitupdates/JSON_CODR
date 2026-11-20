from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping

from web_app.core.contracts import FrozenContract


class RepairProposal(FrozenContract):
    workspace: str
    model_tag: str
    diagnostic_payload: str
    max_attempts: int = 3


class RepairReport(FrozenContract):
    status: str
    attempts: int
    verified: bool


class RepairPipeline:
    def diagnose(self, failure: Mapping[str, object], workspace: str, model_tag: str) -> RepairProposal:
        traceback_text = self._redact(str(failure.get("traceback", "")))[:8_192]
        source = self._redact(str(failure.get("source", "")))[:2_048]
        packages = failure.get("packages", [])
        payload = json.dumps(
            {
                "traceback": traceback_text,
                "source_context": source,
                "packages": packages if isinstance(packages, list) else [],
                "model_tag": model_tag,
                "instruction": "Propose a unified diff only. Do not install packages or mutate live files.",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return RepairProposal(
            workspace=workspace,
            model_tag=model_tag,
            diagnostic_payload=payload,
        )

    def attempt(self, proposal: RepairProposal, verify: Callable[[int], bool]) -> RepairReport:
        for attempt in range(1, proposal.max_attempts + 1):
            if verify(attempt):
                return RepairReport(status="verified", attempts=attempt, verified=True)
        return RepairReport(status="exhausted", attempts=proposal.max_attempts, verified=False)

    @staticmethod
    def _redact(value: str) -> str:
        value = re.sub(r"(?i)(token|password|secret|api[_-]?key)\s*[=:]\s*[^\s,;]+", r"\1=[REDACTED]", value)
        value = re.sub(r"(?i)[A-Z]:[/\\]Users[/\\][^/\\\s]+", "[USER_HOME]", value)
        return value
