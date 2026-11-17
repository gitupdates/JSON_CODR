from __future__ import annotations

import hashlib
from pathlib import Path

from web_app.core.contracts import FrozenContract


class ExternalChangeEvent(FrozenContract):
    project_root: str
    before_fingerprint: str
    after_fingerprint: str
    changed_paths: tuple[str, ...]


class ProjectWatcher:
    def __init__(self, project_root: str | Path) -> None:
        self._root = Path(project_root).resolve()
        self._state: dict[str, str] | None = None

    def snapshot(self) -> str:
        self._state = self._scan()
        return self._fingerprint(self._state)

    def poll(self) -> ExternalChangeEvent | None:
        before = self._state if self._state is not None else self._scan()
        after = self._scan()
        changed = tuple(sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path)))
        self._state = after
        if not changed:
            return None
        return ExternalChangeEvent(
            project_root=str(self._root),
            before_fingerprint=self._fingerprint(before),
            after_fingerprint=self._fingerprint(after),
            changed_paths=changed,
        )

    def _scan(self) -> dict[str, str]:
        result = {}
        for path in self._root.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                result[str(path.relative_to(self._root)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    @staticmethod
    def _fingerprint(state: dict[str, str]) -> str:
        digest = hashlib.sha256()
        for path, value in sorted(state.items()):
            digest.update(f"{path}\0{value}\n".encode())
        return f"sha256:{digest.hexdigest()}"
