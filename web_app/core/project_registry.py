from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from web_app.core.contracts import FrozenContract


class RegisteredProject(FrozenContract):
    project_id: str
    root: str
    root_fingerprint: str
    parent_project_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectRegistry:
    def __init__(self, database: str | Path) -> None:
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS registered_projects (
                project_id TEXT PRIMARY KEY,
                root TEXT NOT NULL UNIQUE,
                root_fingerprint TEXT NOT NULL,
                parent_project_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(registered_projects)")}
        if "parent_project_id" not in columns:
            self._connection.execute("ALTER TABLE registered_projects ADD COLUMN parent_project_id TEXT")
        self._lock = threading.RLock()

    def close(self) -> None:
        self._connection.close()

    def register(
        self,
        root: str | Path,
        *,
        project_id: str | None = None,
        parent_project_id: str | None = None,
    ) -> RegisteredProject:
        supplied = Path(root).absolute()
        self._reject_links(supplied)
        try:
            resolved = supplied.resolve(strict=True)
        except OSError as error:
            raise ValueError("project root must be an existing directory") from error
        if not resolved.is_dir():
            raise ValueError("project root must be an existing directory")
        display_root = str(resolved)
        root_key = self._root_key(display_root)
        stable_id = "project:" + hashlib.sha256(root_key.encode("utf-8")).hexdigest()[:24]
        project_id = project_id or stable_id
        fingerprint = self._root_fingerprint(resolved)
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            if parent_project_id is not None:
                self.resolve(parent_project_id)
            if self._case_insensitive_paths():
                existing = self._connection.execute(
                    "SELECT * FROM registered_projects WHERE root = ? COLLATE NOCASE", (display_root,)
                ).fetchone()
            else:
                existing = self._connection.execute(
                    "SELECT * FROM registered_projects WHERE root = ?", (display_root,)
                ).fetchone()
            if existing is None:
                self._connection.execute(
                    """INSERT INTO registered_projects
                    (project_id, root, root_fingerprint, parent_project_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (project_id, display_root, fingerprint, parent_project_id, now, now),
                )
            elif (
                existing["root_fingerprint"] != fingerprint
                or existing["parent_project_id"] != parent_project_id
            ):
                raise ValueError("registered project root identity changed")
            else:
                project_id = existing["project_id"]
                self._connection.execute(
                    "UPDATE registered_projects SET updated_at = ? WHERE project_id = ?",
                    (now, project_id),
                )
        return self.get(project_id)

    def register_child(self, parent_project_id: str, root: str | Path) -> RegisteredProject:
        return self.register(root, parent_project_id=parent_project_id)

    def get(self, project_id: str) -> RegisteredProject:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM registered_projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError("project is not registered")
        return self._record(row)

    def resolve(self, project_id: str) -> Path:
        record = self.get(project_id)
        root = Path(record.root)
        if not root.exists():
            raise ValueError("registered project root is missing")
        self._reject_links(root)
        resolved = root.resolve(strict=True)
        if self._root_fingerprint(resolved) != record.root_fingerprint:
            raise ValueError("registered project root identity changed")
        return resolved

    def list(self) -> tuple[RegisteredProject, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM registered_projects ORDER BY created_at, project_id"
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    @staticmethod
    def _reject_links(path: Path) -> None:
        current = path
        while True:
            if current.exists():
                stat = current.lstat()
                is_reparse = bool(getattr(stat, "st_file_attributes", 0) & 0x400)
                if current.is_symlink() or is_reparse:
                    raise ValueError("project root cannot contain a link or reparse point")
            if current.parent == current:
                break
            current = current.parent

    @staticmethod
    def _root_fingerprint(root: Path) -> str:
        stat = root.stat()
        material = f"{os.path.normcase(str(root))}\0{stat.st_dev}\0{stat.st_ino}"
        return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _case_insensitive_paths() -> bool:
        return os.name == "nt"

    @classmethod
    def _root_key(cls, root: str | Path, *, case_insensitive: bool | None = None) -> str:
        value = str(root)
        is_case_insensitive = cls._case_insensitive_paths() if case_insensitive is None else case_insensitive
        if is_case_insensitive:
            return value.casefold()
        return value

    @staticmethod
    def _record(row: sqlite3.Row) -> RegisteredProject:
        return RegisteredProject(
            project_id=row["project_id"], root=row["root"],
            root_fingerprint=row["root_fingerprint"],
            parent_project_id=row["parent_project_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
