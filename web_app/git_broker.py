from __future__ import annotations

import hashlib
import os
import stat
import subprocess
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
