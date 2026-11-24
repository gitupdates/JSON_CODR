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

from web_app.core.cli_identity import CliIdentityService, DpapiTokenStore, normalize_server_origin
from web_app.runtime_config import RuntimeConfig


Submitter = Callable[[Mapping[str, Any]], Mapping[str, Any]]
_SENSITIVE = {"api_key", "authorization", "cookie", "credential", "credential_refs", "password", "secret", "token"}


class _RejectAuthenticatedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, _message, _headers, _new_url):
        response.close()
        raise ValueError("authenticated request refused redirect")


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    submit: Submitter | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    auth_service: CliIdentityService | None = None,
) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    if args.action == "auth":
        auth_service = auth_service or _default_auth_service()
        try:
            if args.auth_action == "login":
                result = auth_service.login(
                    args.username,
                    args.password,
                    requested_scopes=tuple(args.scopes),
                    server_origin=args.url,
                )
                print(f"Signed in as {result.account} · {result.label} · expires {result.expires_at.isoformat()}", file=stdout)
            elif args.auth_action == "status":
                principal = auth_service.status()
                print(f"Signed in as {principal.username} · cli · {', '.join(principal.scopes)}", file=stdout)
            elif args.auth_action == "logout":
                auth_service.logout()
                print("CLI credential revoked", file=stdout)
            else:
                parser.print_help(stderr)
                return 64
        except (OSError, PermissionError, ValueError) as error:
            print(f"JSON_CODR authentication failed: {error}", file=stderr)
            return 1
        return 0
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
        if submit is not None:
            result = dict(submit(command))
        else:
            active_auth = auth_service or _default_auth_service()
            try:
                document = active_auth.store.load()
                target_origin = normalize_server_origin(args.url)
            except (PermissionError, ValueError) as error:
                print(f"JSON_CODR authentication failed: {error}", file=stderr)
                return 1
            token = document.get("token")
            if not isinstance(token, str) or not token:
                print("JSON_CODR authentication failed: CLI credential storage is unavailable or corrupt", file=stderr)
                return 1
            if document.get("server_origin") != target_origin:
                print("JSON_CODR authentication failed: CLI credential is bound to a different server origin", file=stderr)
                return 1
            result = dict(_http_submitter(args.url, token)(command))
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


def _default_auth_service() -> CliIdentityService:
    from web_app.core.identity import IdentityService
    from web_app.workspace import default_data_root

    return CliIdentityService(
        IdentityService(default_data_root()),
        DpapiTokenStore(Path.home() / ".json_codr" / "credentials" / "cli.dpapi"),
    )


def _http_submitter(base_url: str, token: str) -> Submitter:
    def submit(command: Mapping[str, Any]) -> Mapping[str, Any]:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}{RuntimeConfig.load().tasks_path}",
            data=json.dumps(command).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        opener = urllib.request.build_opener(_RejectAuthenticatedRedirects())
        with opener.open(request) as response:
            return json.load(response)

    return submit


def _http_status(base_url: str) -> Mapping[str, Any]:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}{RuntimeConfig.load().runtime_status_path}") as response:
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
    runtime = RuntimeConfig.load()
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
    run.add_argument("--url", default=runtime.url)
    status = subparsers.add_parser("status")
    status.add_argument("--output", choices=("text", "json"), default="text")
    status.add_argument("--url", default=runtime.url)
    auth = subparsers.add_parser("auth")
    auth_subparsers = auth.add_subparsers(dest="auth_action")
    login = auth_subparsers.add_parser("login")
    login.add_argument("--username", default="Administrator")
    login.add_argument("--password", default="")
    login.add_argument("--scope", dest="scopes", action="append", default=[])
    login.add_argument("--url", default=runtime.url)
    auth_subparsers.add_parser("status")
    auth_subparsers.add_parser("logout")
    return parser


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
