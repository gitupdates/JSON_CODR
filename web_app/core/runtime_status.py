from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from web_app.core.store import TaskStore


_IDENTITY_ENVIRONMENT = (
    ("revision", "JSON_CODR_REVISION"),
    ("instance_id", "JSON_CODR_INSTANCE_ID"),
    ("started_at", "JSON_CODR_STARTED_AT"),
    ("manifest_digest", "JSON_CODR_ARTIFACT_MANIFEST"),
)
_RUNNING_STATES = frozenset({"running", "ready", "healthy"})


def build_runtime_status(
    store: TaskStore,
    *,
    environment: Mapping[str, str],
    current_pid: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = now or datetime.now(UTC)
    historical = store.runtime_heartbeats(now=observed_at)
    identity = {
        field: (str(environment.get(variable) or "").strip() or None)
        for field, variable in _IDENTITY_ENVIRONMENT
    }
    missing = [field for field, _variable in _IDENTITY_ENVIRONMENT if identity[field] is None]
    heartbeat_managed = any(
        heartbeat.pid == current_pid
        and not heartbeat.stale
        and heartbeat.status in _RUNNING_STATES
        for heartbeat in historical
    )
    try:
        supervisor_pid = int(str(environment.get("JSON_CODR_SUPERVISOR_PID") or ""))
    except ValueError:
        supervisor_pid = None
    launcher_managed = supervisor_pid is not None and supervisor_pid > 0 and supervisor_pid == os.getppid()
    managed = heartbeat_managed or launcher_managed
    management_source = (
        "heartbeat" if heartbeat_managed else "stable-launcher" if launcher_managed else None
    )
    current_process = {
        "runtime_id": "web",
        "pid": current_pid,
        "status": "ready",
        "stale": False,
    }
    return {
        "local_only": True,
        "health": "healthy" if not missing else "degraded",
        "identity_state": "complete" if not missing else "incomplete",
        "missing_identity": missing,
        "management_state": "managed" if managed else "unmanaged",
        "management_source": management_source,
        "supervisor_pid": supervisor_pid if launcher_managed else None,
        **identity,
        "current_process": current_process,
        "heartbeats": [current_process],
        "historical_heartbeats": [
            heartbeat.model_dump(mode="json") for heartbeat in historical
        ],
        "telemetry": [
            item.model_dump(mode="json") for item in store.telemetry()[-100:]
        ],
    }
