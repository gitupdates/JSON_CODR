from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
from pathlib import Path
from uuid import uuid7

from pydantic import Field

from web_app.core.contracts import FrozenContract


class WorktreeSession(FrozenContract):
    session_id: str
    source_root: str
    working_root: str
    baseline_fingerprint: str
    isolation_level: str


class WorktreeRuntime:
    _locks: dict[str, threading.Lock] = {}
    _guard = threading.Lock()

    def __init__(self, state_root: str | Path) -> None:
        self.root = Path(state_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._held: dict[str, threading.Lock] = {}

    def create(self, project_root: str | Path) -> WorktreeSession:
        source = Path(project_root).resolve(strict=True)
        if not source.is_dir() or source.is_symlink():
            raise ValueError("project root must be a real directory")
        key = str(source).casefold()
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        if not lock.acquire(blocking=False):
            raise RuntimeError("project already has an active writer")
        session_id = str(uuid7())
        destination = self.root / session_id
        try:
            if (source / ".git").exists():
                dirty = subprocess.run(
                    ["git", "status", "--porcelain"], cwd=source,
                    check=True, capture_output=True, text=True,
                ).stdout
                if dirty.strip():
                    raise ValueError("isolated worktree requires a clean source repository")
                subprocess.run(
                    ["git", "worktree", "add", "--detach", str(destination), "HEAD"],
                    cwd=source, check=True, capture_output=True, text=True,
                )
                level = "git_worktree"
            else:
                shutil.copytree(source, destination, symlinks=False)
                level = "checkpoint_copy_reduced_isolation"
            session = WorktreeSession(
                session_id=session_id, source_root=str(source), working_root=str(destination),
                baseline_fingerprint=self.fingerprint(source), isolation_level=level,
            )
            self._held[session_id] = lock
            return session
        except Exception:
            lock.release()
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def apply(self, session: WorktreeSession, *, approved_fingerprint: str) -> None:
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
        else:
            for item in working.rglob("*"):
                relative = item.relative_to(working)
                target = source / relative
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif item.is_file() and not item.is_symlink():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)

    def close(self, session: WorktreeSession) -> None:
        working = Path(session.working_root)
        if session.isolation_level == "git_worktree" and working.exists():
            subprocess.run(["git", "worktree", "remove", "--force", str(working)], cwd=session.source_root, capture_output=True)
        else:
            shutil.rmtree(working, ignore_errors=True)
        lock = self._held.pop(session.session_id, None)
        if lock is not None:
            lock.release()

    @staticmethod
    def fingerprint(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink() or ".git" in path.parts:
                continue
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
        return "sha256:" + digest.hexdigest()
