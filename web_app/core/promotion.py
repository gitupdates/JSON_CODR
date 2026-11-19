from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path
from uuid import uuid7

from web_app.core.contracts import FrozenContract


class StagedCandidate(FrozenContract):
    candidate_id: str
    repository_root: str
    worktree_root: str
    branch: str
    base_commit: str


class VerificationManifest(FrozenContract):
    candidate_id: str
    digest: str
    files: tuple[str, ...]
    base_commit: str


class PromotionResult(FrozenContract):
    status: str
    snapshot_id: str
    commit: str


class PromotionService:
    def __init__(self, repository_root: Path, state_root: Path, broker) -> None:
        self.repository_root = repository_root.resolve()
        self.state_root = state_root.resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.broker = broker
        self._manifests: dict[str, VerificationManifest] = {}

    def stage(self, base_ref: str) -> StagedCandidate:
        candidate_id = str(uuid7())
        branch = f"borg-repair-{candidate_id}"
        worktree = self.state_root / "staging" / candidate_id
        base_commit = self._git(self.repository_root, "rev-parse", base_ref)
        values = self.broker.create_worktree(self.repository_root, worktree, branch)
        if values["base_commit"] != base_commit:
            raise RuntimeError("staged candidate base changed during creation")
        return StagedCandidate(candidate_id=candidate_id, **values)

    def verify(self, candidate: StagedCandidate) -> VerificationManifest:
        root = Path(candidate.worktree_root).resolve()
        if not root.is_relative_to(self.state_root):
            raise ValueError("candidate is outside the staging root")
        files = []
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not path.is_file() or ".git" in path.parts or ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            content = path.read_bytes()
            if path.suffix == ".py":
                ast.parse(content.decode("utf-8"), filename=relative)
                compile(content, relative, "exec")
            files.append(relative)
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(content).digest())
        manifest = VerificationManifest(
            candidate_id=candidate.candidate_id,
            digest=f"sha256:{digest.hexdigest()}",
            files=tuple(files),
            base_commit=candidate.base_commit,
        )
        self._manifests[candidate.candidate_id] = manifest
        return manifest

    def promote(self, candidate: StagedCandidate, approval_ref: str) -> PromotionResult:
        approved = self._manifests.get(candidate.candidate_id)
        current = self.verify(candidate)
        if approved is None or approval_ref != approved.digest or current.digest != approved.digest:
            raise PermissionError("promotion approval does not match the verified candidate")
        if self._git(self.repository_root, "rev-parse", "HEAD") != candidate.base_commit:
            raise RuntimeError("live project changed after candidate staging")
        worktree = Path(candidate.worktree_root)
        self._git(worktree, "add", "-A")
        self._git(worktree, "commit", "-m", f"repair: promote {candidate.candidate_id}")
        candidate_commit = self._git(worktree, "rev-parse", "HEAD")
        merged = self.broker.merge_worktree_branch(self.repository_root, candidate.branch)
        return PromotionResult(
            status="promoted",
            snapshot_id=candidate.base_commit,
            commit=merged["commit"] or candidate_commit,
        )

    def rollback(self, snapshot_id: str) -> PromotionResult:
        self._git(self.repository_root, "cat-file", "-e", f"{snapshot_id}^{{commit}}")
        self._git(self.repository_root, "reset", "--hard", snapshot_id)
        return PromotionResult(status="rolled_back", snapshot_id=snapshot_id, commit=snapshot_id)

    @staticmethod
    def _git(root: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "git command failed")
        return completed.stdout.strip()
