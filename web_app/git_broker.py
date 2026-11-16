from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import uuid
from dataclasses import dataclass
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


class GitBrokerService:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.audit_path = self.data_root / "git-broker-audit.json"

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
    def _git(project: Path, *args: str, check: bool = True) -> str:
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        result = subprocess.run(
            ["git", *args], cwd=project, check=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=environment,
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
