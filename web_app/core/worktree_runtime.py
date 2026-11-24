from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

from web_app.core.contracts import FrozenContract


class RepositoryLockOwner(FrozenContract):
    owner_pid: int
    candidate_id: str
    created_at: datetime
    expires_at: datetime
    token: str
    repository_root: str


class RepositoryBusy(RuntimeError):
    def __init__(self, owner: RepositoryLockOwner) -> None:
        self.owner = owner
        super().__init__(
            f"project already has an active writer: candidate {owner.candidate_id} "
            f"owned by PID {owner.owner_pid}"
        )


class WorktreeSession(FrozenContract):
    session_id: str
    candidate_id: str
    source_root: str
    working_root: str
    baseline_fingerprint: str
    isolation_level: str
    branch: str | None = None
    base_sha: str | None = None
    lock_path: str
    lock_token: str


def _default_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class WorktreeRuntime:
    """Owns candidate worktrees and an OS-visible, repository-scoped writer lease."""

    def __init__(
        self,
        state_root: str | Path,
        *,
        lock_ttl: timedelta = timedelta(minutes=30),
        clock: Callable[[], datetime] | None = None,
        process_alive: Callable[[int], bool] | None = None,
    ) -> None:
        self.root = Path(state_root).resolve()
        self.worktree_root = self.root / "worktrees"
        self.lock_root = self.root / "locks"
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        self.lock_root.mkdir(parents=True, exist_ok=True)
        self._lock_ttl = lock_ttl
        self._clock = clock or (lambda: datetime.now(UTC))
        self._process_alive = process_alive or _default_process_alive
        self._held: dict[str, RepositoryLockOwner] = {}

    def create(
        self,
        project_root: str | Path,
        *,
        candidate_id: str | None = None,
    ) -> WorktreeSession:
        source = Path(project_root).resolve(strict=True)
        if not source.is_dir() or source.is_symlink():
            raise ValueError("project root must be a real directory")
        self._assert_no_linked_paths(source)
        is_git = (source / ".git").exists()
        if is_git:
            dirty = self._git(source, "status", "--porcelain", "--untracked-files=all")
            if dirty.strip():
                raise ValueError("isolated worktree requires a clean source repository")
        effective_candidate = candidate_id or f"legacy-{uuid7()}"
        owner, lock_path = self._acquire(source, effective_candidate)
        session_id = str(uuid7())
        destination = self.worktree_root / session_id
        try:
            branch = None
            base_sha = None
            if is_git:
                base_sha = self._git(source, "rev-parse", "HEAD")
                if candidate_id is None:
                    self._git(source, "worktree", "add", "--detach", str(destination), base_sha)
                else:
                    branch = self._candidate_branch(candidate_id)
                    self._git(source, "worktree", "add", "-b", branch, str(destination), base_sha)
                level = "git_worktree"
            else:
                shutil.copytree(source, destination, symlinks=False)
                level = "checkpoint_copy_reduced_isolation"
            session = WorktreeSession(
                session_id=session_id,
                candidate_id=effective_candidate,
                source_root=str(source),
                working_root=str(destination),
                baseline_fingerprint=self.fingerprint(source),
                isolation_level=level,
                branch=branch,
                base_sha=base_sha,
                lock_path=str(lock_path),
                lock_token=owner.token,
            )
            self._held[session_id] = owner
            return session
        except Exception:
            self._release(lock_path, owner.token)
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def resume(self, session: WorktreeSession) -> None:
        working = Path(session.working_root)
        if not working.is_dir():
            raise FileNotFoundError("candidate worktree no longer exists")
        owner = self._read_owner(Path(session.lock_path))
        if owner.token != session.lock_token or owner.candidate_id != session.candidate_id:
            raise RepositoryBusy(owner)
        self._held[session.session_id] = owner

    def apply(self, session: WorktreeSession, *, approved_fingerprint: str) -> None:
        if not session.candidate_id.startswith("legacy-"):
            raise PermissionError("candidate worktrees are authoritative and cannot be copied back")
        source = Path(session.source_root)
        working = Path(session.working_root)
        if approved_fingerprint != session.baseline_fingerprint or self.fingerprint(source) != session.baseline_fingerprint:
            raise PermissionError("source project drifted after approval")
        if session.isolation_level == "git_worktree":
            diff = subprocess.run(
                ["git", "diff", "--binary", "HEAD"], cwd=working,
                check=True, capture_output=True,
            ).stdout
            if diff:
                subprocess.run(["git", "apply", "--binary", "-"], cwd=source, input=diff, check=True)
            return
        for item in working.rglob("*"):
            relative = item.relative_to(working)
            target = source / relative
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif item.is_file() and not item.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)

    def has_changes(self, session: WorktreeSession) -> bool:
        self.resume(session)
        return bool(self._git(Path(session.working_root), "status", "--porcelain", "--untracked-files=all"))

    def tree_sha(self, session: WorktreeSession) -> str:
        self.resume(session)
        working = Path(session.working_root)
        descriptor, index_name = tempfile.mkstemp(prefix="json-codr-candidate-", suffix=".index")
        os.close(descriptor)
        Path(index_name).unlink(missing_ok=True)
        environment = {**os.environ, "GIT_INDEX_FILE": index_name, "GIT_TERMINAL_PROMPT": "0"}
        try:
            self._git(working, "read-tree", "HEAD", environment=environment)
            self._git(working, "add", "--all", environment=environment)
            return self._git(working, "write-tree", environment=environment)
        finally:
            Path(index_name).unlink(missing_ok=True)

    def commit(self, session: WorktreeSession, message: str) -> str:
        self.resume(session)
        if session.isolation_level != "git_worktree" or session.candidate_id.startswith("legacy-"):
            raise PermissionError("only an isolated candidate Git worktree can be committed")
        working = Path(session.working_root)
        self._assert_no_linked_paths(working)
        self._git(working, "add", "--all")
        if not self._git(working, "diff", "--cached", "--name-only"):
            raise ValueError("candidate has no changes to commit")
        self._git(working, "commit", "-m", message.strip())
        commit = self._git(working, "rev-parse", "HEAD")
        if self._git(working, "status", "--porcelain", "--untracked-files=all"):
            raise RuntimeError("candidate worktree is not clean after commit")
        return commit

    def close(self, session: WorktreeSession) -> None:
        working = Path(session.working_root)
        if session.isolation_level == "git_worktree" and working.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(working)],
                cwd=session.source_root, capture_output=True, text=True,
            )
        else:
            shutil.rmtree(working, ignore_errors=True)
        owner = self._held.pop(session.session_id, None)
        self._release(Path(session.lock_path), session.lock_token if owner is None else owner.token)

    @staticmethod
    def fingerprint(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink() or ".git" in path.parts:
                continue
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _candidate_branch(candidate_id: str) -> str:
        safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in candidate_id)
        return f"json-codr/candidate-{safe[:80]}"

    def _acquire(self, source: Path, candidate_id: str) -> tuple[RepositoryLockOwner, Path]:
        canonical = str(source.resolve()).casefold()
        key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        path = self.lock_root / f"{key}.lock"
        now = self._clock()
        owner = RepositoryLockOwner(
            owner_pid=os.getpid(),
            candidate_id=candidate_id,
            created_at=now,
            expires_at=now + self._lock_ttl,
            token=str(uuid7()),
            repository_root=str(source),
        )
        for _ in range(2):
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                existing = self._read_owner(path)
                if existing.expires_at <= now and not self._process_alive(existing.owner_pid):
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                raise RepositoryBusy(existing)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(owner.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            return owner, path
        raise RepositoryBusy(self._read_owner(path))

    @staticmethod
    def _read_owner(path: Path) -> RepositoryLockOwner:
        try:
            return RepositoryLockOwner.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError(f"repository lock metadata is unreadable: {path}") from error

    def _release(self, path: Path, token: str) -> None:
        try:
            owner = self._read_owner(path)
        except FileNotFoundError:
            return
        except RuntimeError:
            return
        if owner.token != token:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @classmethod
    def _assert_no_linked_paths(cls, root: Path) -> None:
        pending = [root]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name == ".git":
                        continue
                    stat = entry.stat(follow_symlinks=False)
                    reparse = bool(getattr(stat, "st_file_attributes", 0) & 0x400)
                    if entry.is_symlink() or reparse:
                        raise ValueError(f"symlink or reparse point is not allowed: {entry.path}")
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))

    @staticmethod
    def _git(
        root: Path,
        *arguments: str,
        environment: dict[str, str] | None = None,
    ) -> str:
        result = subprocess.run(
            ["git", *arguments], cwd=root, check=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=environment,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Git command failed")
        return result.stdout.strip()
