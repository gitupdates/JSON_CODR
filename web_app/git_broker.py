from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from web_app.models import BrokerActionRequest


@dataclass(frozen=True)
class RepositorySnapshot:
    root: str
    head: str
    branch: str | None
    upstream: str | None
    remote_head: str | None
    dirty_fingerprint: str
    clean: bool


@dataclass(frozen=True)
class BrokerActionResult:
    status: str
    snapshot: RepositorySnapshot
    task_id: str | None = None
    commit: str | None = None
    remote: str | None = None
    branch: str | None = None
    outputs: dict = field(default_factory=dict)


class GitBrokerService:
    def __init__(self, data_root: Path, verification_checks: dict[str, list[str]] | None = None) -> None:
        self.data_root = Path(data_root).resolve()
        self.audit_path = self.data_root / "git-broker-audit.json"
        self.verification_checks = verification_checks or {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @staticmethod
    def _project(path: Path | str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_dir():
            raise ValueError("Project root must be an existing directory")
        details = candidate.lstat()
        if candidate.is_symlink() or bool(getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError("Project root cannot be a reparse point")
        return candidate.resolve()

    @staticmethod
    def _git(project: Path, *args: str, check: bool = True, input_text: str | None = None) -> str:
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        result = subprocess.run(
            ["git", *args], cwd=project, check=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=environment, input=input_text,
        )
        if check and result.returncode:
            message = result.stderr.strip() or result.stdout.strip() or "Git command failed"
            raise ValueError(message)
        return result.stdout.strip()

    def validate_request(self, request: BrokerActionRequest) -> BrokerActionRequest:
        self._project(request.project_root)
        return request

    def _read_audit(self) -> list[dict]:
        if not self.audit_path.is_file():
            return []
        try:
            payload = json.loads(self.audit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _write_audit(self, records: list[dict]) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        temporary = self.data_root / f".git-broker-audit-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(records, indent=2), encoding="utf-8")
        os.replace(temporary, self.audit_path)

    def record_audit(self, record: dict) -> dict:
        safe = {key: value for key, value in record.items() if key not in {"prompt", "environment", "content", "patch"}}
        records = self._read_audit()
        existing = next((item for item in records if item.get("id") == safe.get("id")), None)
        if existing is None:
            records.append(safe)
        else:
            existing.update(safe)
            safe = existing
        self._write_audit(records)
        return dict(safe)

    def recover_interrupted_tasks(self) -> list[dict]:
        records = self._read_audit()
        recovered = []
        for record in records:
            if record.get("status") in {"queued", "running"}:
                record["status"] = "interrupted"
                recovered.append(dict(record))
        if recovered:
            self._write_audit(records)
        return recovered

    def _lock(self, project: Path) -> threading.Lock:
        key = str(project).casefold()
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def execute(self, request: BrokerActionRequest, model: str, grant_id: str) -> BrokerActionResult:
        request = self.validate_request(request)
        project = self._project(request.project_root)
        with self._lock(project):
            snapshot = self.inspect(project)
            if snapshot.dirty_fingerprint != request.baseline_fingerprint:
                raise RuntimeError("Project changed since authorization")
            task_id = uuid.uuid4().hex
            self.record_audit({
                "id": task_id, "status": "running", "project_root": str(project),
                "model": model, "profile": "broker", "grant_id": grant_id,
            })
            commit = None
            status = "completed"
            outputs: dict = {"files": {}, "checks": {}, "diff": ""}
            try:
                if snapshot.upstream:
                    self._git(project, "fetch", "--quiet")
                for action in request.actions:
                    if action.kind == "apply_patch":
                        patch = action.patch or ""
                        self._git(project, "apply", "--check", "-", input_text=patch)
                        self._git(project, "apply", "-", input_text=patch)
                    elif action.kind == "read":
                        for relative in action.paths:
                            target = (project / relative).resolve()
                            try:
                                target.relative_to(project)
                            except ValueError as error:
                                raise ValueError("Read path leaves the authorized project") from error
                            if not target.is_file():
                                raise ValueError(f"Project file not found: {relative}")
                            outputs["files"][relative] = target.read_text(encoding="utf-8", errors="replace")
                    elif action.kind == "verify":
                        for check_name in action.checks:
                            argv = self.verification_checks.get(check_name)
                            if not argv:
                                raise ValueError(f"Verification check is not configured: {check_name}")
                            result = subprocess.run(
                                argv, cwd=project, check=False, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                            )
                            if result.returncode:
                                raise RuntimeError(result.stderr.strip() or f"Verification failed: {check_name}")
                            outputs["checks"][check_name] = result.stdout.strip()
                    elif action.kind == "status":
                        summary = self._git(project, "status", "--short", "--untracked-files=all")
                        diff = self._git(project, "diff", "--no-ext-diff", "--")
                        outputs["diff"] = "\n".join(part for part in (summary, diff) if part)
                    elif action.kind == "commit":
                        self._git(project, "add", "--all")
                        message = (action.message or "Apply JSON_CODR model changes").strip()
                        message += (
                            f"\n\nJSON-CODR-Model: {model}\n"
                            "JSON-CODR-Profile: broker\n"
                            f"JSON-CODR-Grant: {grant_id}"
                        )
                        self._git(project, "commit", "-m", message)
                        commit = self._git(project, "rev-parse", "HEAD")
                        status = "committed"
                    elif action.kind == "sync":
                        current = self.inspect(project)
                        if not current.upstream:
                            raise RuntimeError("Checked-out branch has no upstream")
                        self._git(project, "fetch", "--quiet")
                        self._git(project, "rebase", current.upstream)
                    elif action.kind == "push":
                        current = self.inspect(project)
                        if not current.branch or not current.upstream:
                            raise RuntimeError("Checked-out branch must have an upstream")
                        self._git(project, "fetch", "--quiet")
                        self._git(project, "rebase", current.upstream)
                        self._git(project, "push", "origin", f"HEAD:{current.branch}")
                        status = "pushed"
                final = self.inspect(project)
                self.record_audit({"id": task_id, "status": status, "commit": commit, "branch": final.branch})
                return BrokerActionResult(
                    status=status, snapshot=final, task_id=task_id, commit=commit,
                    remote="origin" if status == "pushed" else None, branch=final.branch,
                    outputs=outputs,
                )
            except Exception:
                self.record_audit({"id": task_id, "status": "failed"})
                raise

    def inspect(self, project_root: Path | str) -> RepositorySnapshot:
        project = self._project(project_root)
        if self._git(project, "rev-parse", "--is-inside-work-tree", check=False) != "true":
            raise ValueError("Project root must be a Git repository")
        head = self._git(project, "rev-parse", "HEAD")
        branch = self._git(project, "branch", "--show-current") or None
        upstream = self._git(project, "rev-parse", "--abbrev-ref", "@{upstream}", check=False) or None
        remote_head = self._git(project, "rev-parse", "@{upstream}", check=False) if upstream else None
        status = self._git(project, "status", "--porcelain=v2", "--untracked-files=all")
        fingerprint = hashlib.sha256(status.replace("\r\n", "\n").encode("utf-8")).hexdigest()
        return RepositorySnapshot(
            root=str(project), head=head, branch=branch, upstream=upstream,
            remote_head=remote_head or None, dirty_fingerprint=fingerprint, clean=not bool(status),
        )
