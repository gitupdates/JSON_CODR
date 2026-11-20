from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from pydantic import Field

from web_app.core.contracts import FrozenContract


_COPY_FILES = (
    "settings.json",
    "hardware-benchmarks.json",
    "integrity-benchmarks.json",
    "skillsets.json",
)
_COPY_DIRECTORIES = ("skill_library", "imports", "benchmark-baselines", "localperf")
_SECRET_NAMES = {"api_key", "authorization", "cookie", "credential", "password", "secret", "secrets", "token"}


class MigrationInspection(FrozenContract):
    source: str
    source_digest: str
    candidates: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()


class MigrationReport(FrozenContract):
    source: str
    destination: str
    source_digest: str
    copied: tuple[str, ...] = ()
    archived: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    malformed: tuple[str, ...] = ()
    created_destination: bool = True


class MigrationService:
    def inspect(self, source: str | Path) -> MigrationInspection:
        root = Path(source).resolve()
        if not root.is_dir():
            raise FileNotFoundError(root)
        candidates = []
        for name in (*_COPY_FILES, *_COPY_DIRECTORIES, "sessions", "git-broker-grants.json", "coding-agent-grants.json"):
            if (root / name).exists():
                candidates.append(name)
        excluded = tuple(name for name in ("secrets", "credentials", ".env") if (root / name).exists())
        return MigrationInspection(
            source=str(root),
            source_digest=_tree_digest(root),
            candidates=tuple(candidates),
            excluded=excluded,
        )

    def migrate(self, source: str | Path, destination: str | Path) -> MigrationReport:
        source_root = Path(source).resolve()
        destination_root = Path(destination).resolve()
        inspection = self.inspect(source_root)
        if destination_root.exists():
            raise FileExistsError(destination_root)
        destination_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{destination_root.name}-migration-", dir=destination_root.parent))
        copied: list[str] = []
        archived: list[str] = []
        malformed: list[str] = []
        try:
            for name in _COPY_FILES:
                source_path = source_root / name
                if not source_path.is_file():
                    continue
                target = staging / name
                if name == "settings.json":
                    try:
                        value = json.loads(source_path.read_text(encoding="utf-8"))
                        target.write_text(json.dumps(_sanitize(value), indent=2), encoding="utf-8")
                    except (OSError, ValueError, TypeError):
                        malformed.append(name)
                        continue
                else:
                    shutil.copy2(source_path, target)
                copied.append(name)

            for name in _COPY_DIRECTORIES:
                source_path = source_root / name
                if source_path.is_dir():
                    shutil.copytree(source_path, staging / name)
                    copied.append(name)

            sessions = source_root / "sessions"
            if sessions.is_dir():
                for session in sorted(path for path in sessions.iterdir() if path.is_dir()):
                    manifest = session / "manifest.json"
                    try:
                        value = json.loads(manifest.read_text(encoding="utf-8"))
                        if not isinstance(value, dict) or not isinstance(value.get("messages", []), list):
                            raise ValueError("invalid session manifest")
                    except (OSError, ValueError, TypeError):
                        malformed.append(str(manifest.relative_to(source_root)))
                        continue
                    shutil.copytree(session, staging / "sessions" / session.name)
                    copied.append(str(session.relative_to(source_root)))

            permissions = source_root / "git-broker-grants.json"
            if permissions.is_file():
                try:
                    grants = _sanitize(json.loads(permissions.read_text(encoding="utf-8")))
                    target = staging / "migration" / "permissions.json"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(grants, indent=2), encoding="utf-8")
                    copied.append("migration/permissions.json")
                except (OSError, ValueError, TypeError):
                    malformed.append(permissions.name)

            legacy_agents = source_root / "coding-agent-grants.json"
            if legacy_agents.is_file():
                target = staging / "migration-archive" / legacy_agents.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy_agents, target)
                archived.append(str(target.relative_to(staging)))

            os.replace(staging, destination_root)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        if _tree_digest(source_root) != inspection.source_digest:
            shutil.rmtree(destination_root, ignore_errors=True)
            raise RuntimeError("migration source changed during copy")
        return MigrationReport(
            source=str(source_root),
            destination=str(destination_root),
            source_digest=inspection.source_digest,
            copied=tuple(copied),
            archived=tuple(archived),
            excluded=inspection.excluded,
            malformed=tuple(malformed),
        )

    def verify(self, report: MigrationReport) -> bool:
        source = Path(report.source)
        destination = Path(report.destination)
        if not destination.is_dir() or _tree_digest(source) != report.source_digest:
            return False
        return all((destination / relative).exists() for relative in (*report.copied, *report.archived))

    def rollback(self, report: MigrationReport) -> None:
        destination = Path(report.destination)
        if report.created_destination and destination.exists():
            shutil.rmtree(destination)


def _sanitize(value):
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items() if key.casefold() not in _SECRET_NAMES}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"
