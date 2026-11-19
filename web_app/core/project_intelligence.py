from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from web_app.core.contracts import FrozenContract


class ProjectFile(FrozenContract):
    relative_path: str
    digest: str
    size: int = Field(ge=0)
    content: str


class ProjectInstruction(FrozenContract):
    relative_path: str
    scope: str
    precedence: int = Field(ge=0)
    trust: str
    content: str
    digest: str


class ProjectOmission(FrozenContract):
    relative_path: str
    reason: str
    size: int = Field(ge=0)


class IndexGeneration(FrozenContract):
    generation: int = Field(ge=1)
    project_root: str
    project_fingerprint: str
    parser_generation: str
    row_count: int = Field(ge=0)
    generation_digest: str
    created_at: datetime


class IndexResult(FrozenContract):
    generation: int = Field(ge=1)
    relative_path: str
    digest: str
    score: int = Field(ge=1)
    excerpt: str


class StaleIndex(RuntimeError):
    pass


class CorruptIndex(RuntimeError):
    pass


class ProjectReader:
    DEFAULT_IGNORED_DIRECTORIES = frozenset({
        ".git", ".runtime", ".venv", "__pycache__", "node_modules", "dist", "build",
    })
    SENSITIVE_NAMES = frozenset({
        ".env", ".env.local", ".env.production", ".npmrc", ".pypirc",
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials",
        "credentials.json", "service-account.json", "terraform.tfstate",
    })
    SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")

    def __init__(
        self,
        project_root: str | Path,
        *,
        max_file_bytes: int = 1_048_576,
        max_total_bytes: int = 33_554_432,
        ignored_directories: frozenset[str] | None = None,
    ) -> None:
        self.root = Path(project_root).resolve()
        if not self.root.is_dir():
            raise ValueError("project root must exist")
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.ignored_directories = ignored_directories or self.DEFAULT_IGNORED_DIRECTORIES

    def files(self) -> tuple[ProjectFile, ...]:
        return self.scan()[0]

    def scan(self) -> tuple[tuple[ProjectFile, ...], tuple[ProjectOmission, ...]]:
        result: list[ProjectFile] = []
        omissions: list[ProjectOmission] = []
        total = 0
        for path in sorted(self.root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.root)
            if any(part in self.ignored_directories for part in relative.parts[:-1]):
                continue
            size = path.stat().st_size
            if self._is_sensitive(relative):
                omissions.append(ProjectOmission(relative_path=relative.as_posix(), reason="sensitive_path", size=size))
                continue
            if size > self.max_file_bytes:
                omissions.append(ProjectOmission(relative_path=relative.as_posix(), reason="oversized", size=size))
                continue
            if total + size > self.max_total_bytes:
                omissions.append(ProjectOmission(relative_path=relative.as_posix(), reason="total_budget", size=size))
                continue
            content_bytes = path.read_bytes()
            if b"\x00" in content_bytes:
                omissions.append(ProjectOmission(relative_path=relative.as_posix(), reason="binary", size=size))
                continue
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                omissions.append(ProjectOmission(relative_path=relative.as_posix(), reason="non_utf8", size=size))
                continue
            total += size
            result.append(ProjectFile(
                relative_path=relative.as_posix(),
                digest=f"sha256:{hashlib.sha256(content_bytes).hexdigest()}",
                size=size,
                content=content,
            ))
        return tuple(result), tuple(omissions)

    @classmethod
    def _is_sensitive(cls, relative: Path) -> bool:
        name = relative.name.casefold()
        parts = {part.casefold() for part in relative.parts}
        return (
            name in cls.SENSITIVE_NAMES
            or name.startswith(".env.")
            or name.endswith(cls.SENSITIVE_SUFFIXES)
            or ".aws" in parts
            or ".azure" in parts
            or ".kube" in parts
            or ".ssh" in parts
        )

    def fingerprint(self, files: tuple[ProjectFile, ...] | None = None) -> str:
        digest = hashlib.sha256()
        for item in self.files() if files is None else files:
            digest.update(f"{item.relative_path}\0{item.digest}\0{item.size}\n".encode("utf-8"))
        return f"sha256:{digest.hexdigest()}"

    def instructions_for(self, target_path: str | Path) -> tuple[ProjectInstruction, ...]:
        target = (self.root / target_path).resolve() if not Path(target_path).is_absolute() else Path(target_path).resolve()
        if target != self.root and not target.is_relative_to(self.root):
            raise ValueError("instruction target escapes project root")
        directory = target if target.is_dir() else target.parent
        relative_directory = directory.relative_to(self.root)
        directories = [self.root]
        current = self.root
        for part in relative_directory.parts:
            current = current / part
            directories.append(current)
        result = []
        for precedence, scope in enumerate(directories):
            candidate = scope / "AGENTS.md"
            if not candidate.is_file() or candidate.is_symlink():
                continue
            content_bytes = candidate.read_bytes()
            if len(content_bytes) > self.max_file_bytes or b"\x00" in content_bytes:
                continue
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue
            result.append(ProjectInstruction(
                relative_path=candidate.relative_to(self.root).as_posix(),
                scope=scope.relative_to(self.root).as_posix(),
                precedence=precedence,
                trust=(
                    "untrusted_project_instruction" if scope == self.root
                    else "untrusted_scoped_project_instruction"
                ),
                content=content,
                digest=f"sha256:{hashlib.sha256(content_bytes).hexdigest()}",
            ))
        return tuple(result)


class RepositoryIndex:
    def __init__(self, database: str | Path, *, parser_generation: str = "regex-symbols-v1") -> None:
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.parser_generation = parser_generation
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS repository_generations (
                generation INTEGER PRIMARY KEY,
                project_root TEXT NOT NULL,
                project_fingerprint TEXT NOT NULL,
                parser_generation TEXT NOT NULL DEFAULT 'regex-symbols-v1',
                row_count INTEGER NOT NULL DEFAULT 0,
                generation_digest TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS repository_files (
                generation INTEGER NOT NULL REFERENCES repository_generations(generation) ON DELETE CASCADE,
                relative_path TEXT NOT NULL,
                digest TEXT NOT NULL,
                content TEXT NOT NULL,
                symbols TEXT NOT NULL,
                PRIMARY KEY(generation, relative_path)
            );
            """
        )
        columns = {
            row["name"] for row in self._connection.execute("PRAGMA table_info(repository_generations)")
        }
        if "parser_generation" not in columns:
            self._connection.execute(
                "ALTER TABLE repository_generations ADD COLUMN parser_generation TEXT NOT NULL DEFAULT 'regex-symbols-v1'"
            )
        if "row_count" not in columns:
            self._connection.execute("ALTER TABLE repository_generations ADD COLUMN row_count INTEGER NOT NULL DEFAULT 0")
        if "generation_digest" not in columns:
            self._connection.execute("ALTER TABLE repository_generations ADD COLUMN generation_digest TEXT NOT NULL DEFAULT ''")

    def close(self) -> None:
        self._connection.close()

    def rebuild(self, reader: ProjectReader) -> IndexGeneration:
        files = reader.files()
        fingerprint = reader.fingerprint(files)
        indexed = []
        for item in files:
            symbols = "\n".join(re.findall(
                r"(?m)^\s*(?:async\s+def|def|class|function|interface|type)\s+([A-Za-z_$][\w$]*)",
                item.content,
            ))
            indexed.append((item, symbols))
        manifest = "\n".join(f"{item.relative_path}\0{item.digest}\0{symbols}" for item, symbols in indexed)
        generation_digest = f"sha256:{hashlib.sha256((self.parser_generation + '\n' + manifest).encode()).hexdigest()}"
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(generation), 0) + 1 AS generation FROM repository_generations"
            ).fetchone()
            generation_number = int(row["generation"])
            generation = IndexGeneration(
                generation=generation_number,
                project_root=str(reader.root),
                project_fingerprint=fingerprint,
                parser_generation=self.parser_generation,
                row_count=len(indexed), generation_digest=generation_digest,
                created_at=datetime.now(UTC),
            )
            self._connection.execute(
                "INSERT INTO repository_generations(generation, project_root, project_fingerprint, parser_generation, row_count, generation_digest, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    generation.generation, generation.project_root,
                    generation.project_fingerprint, generation.parser_generation,
                    generation.row_count, generation.generation_digest,
                    generation.created_at.isoformat(),
                ),
            )
            for item, symbols in indexed:
                self._connection.execute(
                    "INSERT INTO repository_files VALUES (?, ?, ?, ?, ?)",
                    (generation.generation, item.relative_path, item.digest, item.content, symbols),
                )
        return generation

    def search(self, reader: ProjectReader, query: str, limit: int = 20) -> tuple[IndexResult, ...]:
        if not query.strip():
            return ()
        with self._lock:
            generation = self.latest_generation(reader)
            if generation is None:
                return ()
            if generation.project_fingerprint != reader.fingerprint():
                raise StaleIndex("repository index does not match the current project snapshot")
            if generation.parser_generation != self.parser_generation:
                raise StaleIndex("repository index was built by another parser generation")
            rows = self._connection.execute(
                "SELECT * FROM repository_files WHERE generation = ?",
                (generation.generation,),
            ).fetchall()
            manifest = "\n".join(f"{row['relative_path']}\0{row['digest']}\0{row['symbols']}" for row in rows)
            actual_manifest = f"sha256:{hashlib.sha256((generation.parser_generation + chr(10) + manifest).encode()).hexdigest()}"
            if len(rows) != generation.row_count or actual_manifest != generation.generation_digest:
                raise CorruptIndex("repository index generation manifest mismatch")
        needle = query.casefold()
        results = []
        for row in rows:
            actual_digest = f"sha256:{hashlib.sha256(row['content'].encode('utf-8')).hexdigest()}"
            if actual_digest != row["digest"]:
                raise CorruptIndex(f"repository index content digest mismatch for {row['relative_path']}")
            haystack = f"{row['relative_path']}\n{row['symbols']}\n{row['content']}".casefold()
            score = haystack.count(needle)
            if score == 0:
                continue
            content = row["content"]
            position = content.casefold().find(needle)
            start = max(0, position - 120) if position >= 0 else 0
            excerpt = content[start:start + 320]
            results.append(IndexResult(
                generation=generation.generation,
                relative_path=row["relative_path"],
                digest=row["digest"],
                score=score,
                excerpt=excerpt,
            ))
        results.sort(key=lambda item: (-item.score, item.relative_path))
        return tuple(results[:limit])

    def search_rebuilding(self, reader: ProjectReader, query: str, limit: int = 20) -> tuple[IndexResult, ...]:
        try:
            return self.search(reader, query, limit)
        except (CorruptIndex, StaleIndex, sqlite3.DatabaseError):
            self.rebuild(reader)
            return self.search(reader, query, limit)

    def latest_generation(self, reader: ProjectReader) -> IndexGeneration | None:
        row = self._connection.execute(
            "SELECT * FROM repository_generations WHERE project_root = ? ORDER BY generation DESC LIMIT 1",
            (str(reader.root),),
        ).fetchone()
        if row is None:
            return None
        return IndexGeneration(
            generation=row["generation"], project_root=row["project_root"],
            project_fingerprint=row["project_fingerprint"],
            parser_generation=row["parser_generation"],
            row_count=row["row_count"], generation_digest=row["generation_digest"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
