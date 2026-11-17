from __future__ import annotations

import hashlib
import json
import subprocess

from web_app.core.component_registry import ComponentPlan
from web_app.core.component_runtime import InstalledRuntime
from web_app.core.contracts import FrozenContract


class ProbeObservation(FrozenContract):
    succeeded: bool
    exit_code: int
    output: str
    evidence_digest: str


class ComponentProbe:
    def probe(self, plan: ComponentPlan, runtime: InstalledRuntime, *, timeout: float = 30) -> ProbeObservation:
        if not plan.executable:
            output, exit_code = "resource-only component", 0
        elif not runtime.entry_points:
            output, exit_code = "no runnable entry point was installed", 127
        else:
            command = next(iter(runtime.entry_points.values()))
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
            output = (completed.stdout + completed.stderr).strip()
            exit_code = completed.returncode
        evidence = json.dumps({"component_id": plan.component_id, "exit_code": exit_code, "output": output}, sort_keys=True)
        return ProbeObservation(
            succeeded=exit_code == 0, exit_code=exit_code, output=output,
            evidence_digest="sha256:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        )
