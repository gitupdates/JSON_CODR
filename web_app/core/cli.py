from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4


Submitter = Callable[[Mapping[str, Any]], Mapping[str, Any]]
_SENSITIVE = {"api_key", "authorization", "cookie", "credential", "credential_refs", "password", "secret", "token"}


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    submit: Submitter | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    if args.action == "status":
        try:
            result = dict(submit({}) if submit is not None else _http_status(args.url))
        except (OSError, ValueError, urllib.error.HTTPError) as error:
            print(f"JSON_CODR request failed: {error}", file=stderr)
            return 1
        safe_result = _redact(result)
        if args.output == "json":
            print(json.dumps(safe_result, ensure_ascii=False, separators=(",", ":")), file=stdout)
        else:
            locality = "LOCAL ONLY" if safe_result.get("local_only") else "EXTERNAL ROUTES ENABLED"
            print(f"{locality} · {safe_result.get('health', 'unknown')}", file=stdout)
            for heartbeat in safe_result.get("heartbeats", []):
                if isinstance(heartbeat, Mapping):
                    state = "stale" if heartbeat.get("stale") else heartbeat.get("status", "unknown")
                    print(f"{heartbeat.get('runtime_id', 'runtime')} · {state}", file=stdout)
        return 0 if safe_result.get("health") == "healthy" else 1
    if args.action != "run":
        parser.print_help(stderr)
        return 64

    project_root = str(Path(args.project).resolve())
    nonce = uuid4().hex
    command = {
        "schema_version": "1",
        "command_id": f"cli-{nonce}",
        "task_id": f"task-{nonce}",
        "thread_id": args.thread or f"cli-{sha256(project_root.encode()).hexdigest()[:16]}",
        "project_id": args.project_id or f"project-{sha256(project_root.encode()).hexdigest()[:16]}",
        "command_type": "capability.execute",
        "payload": {
            "capability_id": args.capability,
            "operation": args.operation,
            "project_root": project_root,
            "mode": "native",
            "arguments": {"prompt": args.prompt},
        },
    }
    try:
        result = dict((submit or _http_submitter(args.url))(command))
    except (OSError, ValueError, urllib.error.HTTPError) as error:
        print(f"JSON_CODR request failed: {error}", file=stderr)
        return 1
    safe_result = _redact(result)
    events = safe_result.get("events", [])
    if args.output == "json":
        print(json.dumps(safe_result, ensure_ascii=False, separators=(",", ":")), file=stdout)
    elif args.output == "stream-json":
        for event in events if isinstance(events, list) else []:
            print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), file=stdout)
    else:
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, Mapping):
                continue
            payload = event.get("payload", {})
            text = payload.get("text") if isinstance(payload, Mapping) else None
            label = _event_label(event)
            print(f"{label} · {text}" if isinstance(text, str) else label, file=stdout)

    if any(isinstance(event, Mapping) and event.get("event_type") == "task.permission_required" for event in events):
        return 2
    return 0 if safe_result.get("status") == "completed" else 1


def _http_submitter(base_url: str) -> Submitter:
    def submit(command: Mapping[str, Any]) -> Mapping[str, Any]:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/tasks",
            data=json.dumps(command).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    return submit


def _http_status(base_url: str) -> Mapping[str, Any]:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/runtime/status") as response:
        return json.load(response)


def _event_label(event: Mapping[str, Any]) -> str:
    payload = event.get("payload", {})
    if not isinstance(payload, Mapping):
        return str(event.get("event_type", "event"))
    route = payload.get("execution_route") or payload.get("route")
    executor = payload.get("primitive_id") or payload.get("adapter_id")
    parts = [str(item) for item in (route, executor) if item]
    requested = payload.get("requested_model_id")
    effective = payload.get("effective_model_id")
    if requested or effective:
        parts.append(f"{requested or 'not reported'} → {effective or 'not reported'}")
    approval = payload.get("approval_state")
    verification = payload.get("verification_status")
    retries = payload.get("retry_count")
    rollback = payload.get("rollback_status")
    if approval:
        parts.append(f"approval {approval}")
    if verification:
        parts.append(f"verified {verification}")
    if retries is not None:
        parts.append(f"retries {retries}")
    if rollback:
        parts.append(f"rollback {rollback}")
    return " · ".join(parts) or str(event.get("event_type", "event"))


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _redact(item) for key, item in value.items() if key.casefold() not in _SENSITIVE}
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="json-codr")
    subparsers = parser.add_subparsers(dest="action")
    run = subparsers.add_parser("run")
    run.add_argument("prompt")
    run.add_argument("--project", required=True)
    run.add_argument("--project-id")
    run.add_argument("--thread")
    run.add_argument("--capability", default="inference.generate")
    run.add_argument("--operation", default="generate")
    run.add_argument("--output", choices=("text", "json", "stream-json"), default="text")
    run.add_argument("--url", default="http://127.0.0.1:8772")
    status = subparsers.add_parser("status")
    status.add_argument("--output", choices=("text", "json"), default="text")
    status.add_argument("--url", default="http://127.0.0.1:8772")
    return parser


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
