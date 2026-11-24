from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from web_app.core.git_adapter import VerificationReceipt
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
    ahead: int | None = None
    behind: int | None = None


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
    _MAX_OUTPUT_BYTES = 200_000

    def __init__(self, data_root: Path, verification_checks: dict[str, list[str]] | None = None) -> None:
        self.data_root = Path(data_root).resolve()
        self.audit_path = self.data_root / "git-broker-audit.json"
        self.verification_checks = verification_checks or {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._audit_lock = threading.Lock()

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
        return result.stdout[:GitBrokerService._MAX_OUTPUT_BYTES].strip()

    @staticmethod
    def _safe_target(project: Path, relative: str, *, must_exist: bool = False) -> Path:
        target = project / relative
        try:
            target.resolve(strict=False).relative_to(project)
        except ValueError as error:
            raise ValueError("Project path leaves the authorized project") from error
        current = project
        for part in Path(relative).parts:
            current /= part
            if not current.exists():
                continue
            details = current.lstat()
            if current.is_symlink() or bool(getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError("Project paths cannot traverse a reparse point")
        if must_exist and not target.is_file():
            raise ValueError(f"Project file not found: {relative}")
        return target

    @staticmethod
    def _patch_paths(patch: str) -> list[str]:
        paths = []
        for line in patch.splitlines():
            if not line.startswith(("+++ ", "--- ")):
                continue
            value = line[4:].split("\t", 1)[0]
            if value == "/dev/null":
                continue
            expected = "b/" if line.startswith("+++ ") else "a/"
            if not value.startswith(expected):
                raise ValueError("Patch targets must use project-relative a/ and b/ paths")
            relative = value[2:]
            normalized = relative.replace("\\", "/")
            if not normalized or normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
                raise ValueError("Patch path leaves the authorized project")
            paths.append(relative)
        if not paths:
            raise ValueError("Patch does not contain a target file")
        return list(dict.fromkeys(paths))

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
        with self._audit_lock:
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

    def execute(
        self,
        request: BrokerActionRequest,
        model: str,
        grant_id: str,
        authorized: Callable[[], bool] | None = None,
        *,
        verification_receipt: VerificationReceipt | None = None,
        verification_runner: Callable[..., VerificationReceipt] | None = None,
        receipt_validator: Callable[[VerificationReceipt], bool] | None = None,
    ) -> BrokerActionResult:
        request = self.validate_request(request)
        project = self._project(request.project_root)
        with self._lock(project):
            if authorized is not None and not authorized():
                raise PermissionError("Authorization was revoked")
            snapshot = self.inspect(project)
            if snapshot.dirty_fingerprint != request.baseline_fingerprint:
                raise RuntimeError("Project changed since authorization")
            task_id = uuid.uuid4().hex
            self.record_audit({
                "id": task_id, "status": "running", "project_root": str(project),
                "model": model, "profile": "broker", "grant_id": grant_id,
            })
            commit = None
            receipt = verification_receipt
            base_sha = snapshot.head
            touched_paths: list[str] = []
            status = "completed"
            outputs: dict = {"files": {}, "checks": {}, "diff": ""}
            try:
                for action in request.actions:
                    if authorized is not None and not authorized():
                        raise PermissionError("Authorization was revoked")
                    if action.kind == "apply_patch":
                        patch = action.patch or ""
                        action_paths = self._patch_paths(patch)
                        for relative in action_paths:
                            self._safe_target(project, relative)
                        self._git(project, "apply", "--check", "-", input_text=patch)
                        self._git(project, "apply", "-", input_text=patch)
                        touched_paths.extend(action_paths)
                    elif action.kind == "read":
                        for relative in action.paths:
                            target = self._safe_target(project, relative, must_exist=True)
                            outputs["files"][relative] = target.read_text(
                                encoding="utf-8", errors="replace"
                            )[:self._MAX_OUTPUT_BYTES]
                    elif action.kind == "verify":
                        base_sha = self._git(project, "rev-parse", "HEAD")
                        tree_sha = self._tree_sha(project)
                        if verification_runner is not None:
                            receipt = verification_runner(
                                action, candidate_id=grant_id, base_sha=base_sha, tree_sha=tree_sha,
                            )
                            if not isinstance(receipt, VerificationReceipt):
                                raise RuntimeError("Verification did not produce a trusted receipt")
                            if receipt.checks != tuple(action.checks):
                                raise RuntimeError("verification receipt does not cover the requested profiles")
                            outputs["checks"] = {name: "verified" for name in receipt.checks}
                        else:
                            raise RuntimeError("trusted verification runner is not configured")
                    elif action.kind == "status":
                        summary = self._git(project, "status", "--short", "--untracked-files=all")
                        diff = self._git(project, "diff", "--no-ext-diff", "--")
                        outputs["diff"] = "\n".join(part for part in (summary, diff) if part)
                    elif action.kind == "commit":
                        if not touched_paths:
                            raise RuntimeError("Commit requires files changed by an apply_patch action")
                        self._require_receipt(
                            project, receipt, receipt_validator, candidate_id=grant_id, base_sha=base_sha,
                            phase="commit",
                        )
                        self._git(project, "add", "--all")
                        if self._git(project, "write-tree") != receipt.tree_sha:
                            raise RuntimeError("staged candidate tree does not match final verification receipt")
                        message = (action.message or "Apply JSON_CODR model changes").strip()
                        message += (
                            f"\n\nJSON-CODR-Model: {model}\n"
                            "JSON-CODR-Profile: broker\n"
                            f"JSON-CODR-Grant: {grant_id}"
                        )
                        self._git(project, "commit", "-m", message)
                        commit = self._git(project, "rev-parse", "HEAD")
                        if self._git(project, "rev-parse", "HEAD^{tree}") != receipt.tree_sha:
                            raise RuntimeError("commit tree does not match final verification receipt")
                        if not self.inspect(project).clean:
                            raise RuntimeError("candidate worktree is not clean after commit")
                        status = "committed"
                    elif action.kind == "sync":
                        current = self.inspect(project)
                        if not current.upstream:
                            raise RuntimeError("Checked-out branch has no upstream")
                        self._git(project, "fetch", "--quiet")
                        self._git(project, "rebase", current.upstream)
                    elif action.kind == "push":
                        self._require_receipt(
                            project, receipt, receipt_validator, candidate_id=grant_id, base_sha=base_sha,
                            phase="push",
                        )
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

    @classmethod
    def _tree_sha(cls, project: Path) -> str:
        descriptor, index_path = tempfile.mkstemp(prefix="json-codr-tree-", suffix=".index")
        os.close(descriptor)
        os.unlink(index_path)
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_INDEX_FILE": index_path}

        def git_index(*args: str) -> str:
            result = subprocess.run(
                ["git", *args], cwd=project, check=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=environment,
            )
            if result.returncode:
                raise ValueError(result.stderr.strip() or result.stdout.strip() or "Git tree calculation failed")
            return result.stdout.strip()

        try:
            git_index("read-tree", "HEAD")
            git_index("add", "--all")
            return git_index("write-tree")
        finally:
            Path(index_path).unlink(missing_ok=True)

    @classmethod
    def _require_receipt(
        cls,
        project: Path,
        receipt: VerificationReceipt | None,
        receipt_validator: Callable[[VerificationReceipt], bool] | None,
        *,
        candidate_id: str,
        base_sha: str,
        phase: str,
    ) -> None:
        if receipt is None or receipt_validator is None or not receipt_validator(receipt):
            raise RuntimeError("publication requires a trusted final verification receipt")
        if receipt.candidate_id != candidate_id:
            raise RuntimeError("verification receipt belongs to a different candidate")
        if receipt.base_sha != base_sha:
            raise RuntimeError("verification receipt belongs to a different base")
        if phase == "commit" and cls._git(project, "rev-parse", "HEAD") != receipt.base_sha:
            raise RuntimeError("candidate base changed after verification")
        if cls._tree_sha(project) != receipt.tree_sha:
            raise RuntimeError("candidate final tree changed after verification")
        if phase == "push":
            if cls._git(project, "rev-parse", "HEAD^{tree}") != receipt.tree_sha:
                raise RuntimeError("commit tree does not match final verification receipt")
            if not cls._git(project, "status", "--porcelain=v2", "--untracked-files=all") == "":
                raise RuntimeError("candidate worktree is not clean before push")

    def inspect(self, project_root: Path | str) -> RepositorySnapshot:
        project = self._project(project_root)
        if self._git(project, "rev-parse", "--is-inside-work-tree", check=False) != "true":
            raise ValueError("Project root must be a Git repository")
        head = self._git(project, "rev-parse", "HEAD")
        branch = self._git(project, "branch", "--show-current") or None
        upstream = self._git(project, "rev-parse", "--abbrev-ref", "@{upstream}", check=False) or None
        remote_head = self._git(project, "rev-parse", "@{upstream}", check=False) if upstream else None
        ahead = behind = None
        if upstream:
            counts = self._git(project, "rev-list", "--left-right", "--count", f"HEAD...{upstream}", check=False)
            try:
                local_count, upstream_count = (int(value) for value in counts.split())
                ahead, behind = local_count, upstream_count
            except (ValueError, TypeError):
                # Keep the counts unknown if the configured tracking ref cannot be compared.
                ahead = behind = None
        status = self._git(project, "status", "--porcelain=v2", "--untracked-files=all")
        digest = hashlib.sha256()
        digest.update(f"head={head}\nbranch={branch}\nupstream={upstream}\n".encode("utf-8"))
        digest.update(status.replace("\r\n", "\n").encode("utf-8"))
        changed = self._git(project, "status", "--porcelain", "-z", "--untracked-files=all")
        for record in changed.split("\0"):
            if not record:
                continue
            relative = record.split(" ", 1)[1] if " " in record else ""
            if " -> " in relative:
                relative = relative.split(" -> ", 1)[1]
            target = project / relative
            digest.update(relative.encode("utf-8", errors="replace"))
            if target.is_file():
                with target.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
        fingerprint = digest.hexdigest()
        return RepositorySnapshot(
            root=str(project), head=head, branch=branch, upstream=upstream,
            remote_head=remote_head or None, dirty_fingerprint=fingerprint, clean=not bool(status),
            ahead=ahead, behind=behind,
        )

    def create_worktree(self, project_root: Path | str, worktree_root: Path | str, branch: str) -> dict[str, str]:
        project = self._project(project_root)
        worktree = Path(worktree_root).resolve()
        base_commit = self._git(project, "rev-parse", "HEAD")
        self._git(project, "worktree", "add", "-b", branch, str(worktree), base_commit)
        return {
            "repository_root": str(project),
            "worktree_root": str(worktree),
            "branch": branch,
            "base_commit": base_commit,
        }

    def merge_worktree_branch(self, project_root: Path | str, branch: str) -> dict[str, str]:
        project = self._project(project_root)
        output = self._git(project, "merge", "--no-ff", branch, "-m", f"Merge {branch}")
        return {"branch": branch, "commit": self._git(project, "rev-parse", "HEAD"), "output": output}
