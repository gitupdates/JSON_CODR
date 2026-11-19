from __future__ import annotations

import hashlib
import json
import os
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
            observations = []
            exit_code = 0
            commands = runtime.entry_points
            if runtime.runtime_kind == "executable":
                cli_bases = {name[:-4] for name in commands if name.endswith("-cli")}
                commands = {name: command for name, command in commands.items() if name not in cli_bases}
            if len(commands) > 64:
                raise ValueError("component exposes more than 64 commands")
            environment = _probe_environment()
            command_timeout = max(1.0, timeout / len(commands))
            for name, command in commands.items():
                try:
                    completed = subprocess.run(
                        (*command, "--help"), capture_output=True, text=True, timeout=command_timeout,
                        cwd=runtime.runtime_root, env=environment,
                    )
                    text = (completed.stdout + completed.stderr).strip()
                    observations.append(f"[{name}] exit={completed.returncode}\n{text}")
                    if completed.returncode and exit_code == 0:
                        exit_code = completed.returncode
                except (OSError, subprocess.TimeoutExpired) as error:
                    code = 124 if isinstance(error, subprocess.TimeoutExpired) else 127
                    observations.append(f"[{name}] exit={code}\n{type(error).__name__}: {error}")
                    if exit_code == 0:
                        exit_code = code
            output = "\n".join(observations)
        evidence = json.dumps({"component_id": plan.component_id, "exit_code": exit_code, "output": output}, sort_keys=True)
        return ProbeObservation(
            succeeded=exit_code == 0, exit_code=exit_code, output=output,
            evidence_digest="sha256:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        )


def _probe_environment() -> dict[str, str]:
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}
