from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from web_app.core.project_registry import ProjectRegistry
from web_app.models import ProjectSessionRestoreResult, ProjectSessionSnapshot, SessionRecord
from web_app.workspace import SESSION_ID_PATTERN, WorkspaceService


SNAPSHOT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED_TREES = ("originals", "extracted", "artifacts")
_STAGING_PATTERN = re.compile(r"^\.staging-[0-9a-f]{32}$")
_STORAGE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_EXTRACTED_PATTERN = re.compile(r"^[0-9a-f]{32}\.txt$")


class ProjectSessionService:
    """Creates immutable, project-bound copies of complete live sessions."""

    def __init__(self, workspace: WorkspaceService, projects: ProjectRegistry) -> None:
        self.workspace = workspace
        self.projects = projects
        self.root = self.workspace.data_root / "project-sessions"
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _project_key(project_id: str) -> str:
        return hashlib.sha256(project_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_snapshot_id(snapshot_id: str) -> None:
        if not SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id):
            raise ValueError("Invalid snapshot ID")

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        details = path.lstat()
        return path.is_symlink() or bool(
            getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )

    def _reject_reparse_tree(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        if self._is_reparse_point(path):
            raise ValueError("Session snapshot source contains a link or reparse point")
        if path.is_dir():
            for child in path.iterdir():
                self._reject_reparse_tree(child)

    def project_directory(self, project_id: str) -> Path:
        self.projects.resolve(project_id)
        directory = self.root / self._project_key(project_id)
        self._check_chain(directory)
        return directory

    def snapshot_directory(self, snapshot_id: str, project_id: str) -> Path:
        self._validate_snapshot_id(snapshot_id)
        directory = self.project_directory(project_id) / "sessions" / snapshot_id
        self._check_chain(directory)
        return directory

    def _check_chain(self, candidate: Path) -> None:
        trusted = self.workspace.data_root.resolve()
        absolute = candidate.absolute()
        if absolute != trusted and trusted not in absolute.parents:
            raise ValueError("Snapshot path escapes the data root")
        current = trusted
        relative = absolute.relative_to(trusted)
        for part in relative.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                if self._is_reparse_point(current):
                    raise ValueError("Snapshot path contains a link or reparse point")

    def save(
        self,
        session_id: str,
        project_id: str,
        owner_user_id: str,
        title: str,
        change_type: str,
        keywords: list[str],
    ) -> ProjectSessionSnapshot:
        self.projects.resolve(project_id)
        with self.workspace.session_lock(session_id):
            session = self.workspace.get_session(session_id)
            self._require_live_identity(session, project_id, owner_user_id)
            snapshot_id = uuid.uuid4().hex
            snapshot = ProjectSessionSnapshot(
                id=snapshot_id,
                source_session_id=session.id,
                project_id=project_id,
                owner_user_id=owner_user_id,
                title=title.strip(),
                change_type=change_type.strip(),
                keywords=self._keywords(session, snapshot_id, project_id, title, change_type, keywords),
                summary=self._summary(session, title, change_type),
                created_at=datetime.now(timezone.utc),
            )
            if not snapshot.title or not snapshot.change_type:
                raise ValueError("Snapshot title and change type are required")
            final = self.snapshot_directory(snapshot.id, project_id)
            sessions_root = final.parent
            sessions_root.mkdir(parents=True, exist_ok=True)
            self._check_chain(sessions_root)
            self._sweep_staging(sessions_root)
            staging = sessions_root / f".staging-{snapshot.id}"
            try:
                staging.mkdir()
                digests = self._copy_live_session(session, staging)
                self._write_json(staging / "snapshot.json", {
                    "snapshot": snapshot.model_dump(mode="json"),
                    "tree_digests": digests,
                })
                self._write_text(staging / "previous-session-history.md", self._history_markdown(snapshot))
                self._validate_snapshot_tree(staging, digests)
                self._fsync_tree(staging)
                os.replace(staging, final)
                self._fsync_directory(final.parent)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            return snapshot

    def list(self, project_id: str, owner_user_id: str, query: str = "") -> list[ProjectSessionSnapshot]:
        directory = self.project_directory(project_id) / "sessions"
        if not directory.exists():
            return []
        records: list[ProjectSessionSnapshot] = []
        needle = query.strip().casefold()
        for candidate in sorted(directory.iterdir(), key=lambda path: path.name):
            if candidate.name.startswith(".") or self._is_reparse_point(candidate) or not candidate.is_dir():
                continue
            try:
                record = self._read_snapshot(candidate)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if record.project_id != project_id or record.owner_user_id != owner_user_id:
                continue
            haystack = " ".join([record.title, record.change_type, record.summary, *record.keywords]).casefold()
            if not needle or needle in haystack:
                records.append(record)
        return sorted(records, key=lambda record: (record.created_at, record.id), reverse=True)

    def get(self, snapshot_id: str, project_id: str, owner_user_id: str) -> ProjectSessionSnapshot:
        self.projects.resolve(project_id)
        path = self.snapshot_directory(snapshot_id, project_id)
        if not path.is_dir():
            raise KeyError(snapshot_id)
        record = self._read_snapshot(path)
        if record.project_id != project_id or record.owner_user_id != owner_user_id:
            raise KeyError(snapshot_id)
        return record

    def restore(self, snapshot_id: str, project_id: str, owner_user_id: str) -> ProjectSessionRestoreResult:
        snapshot = self.get(snapshot_id, project_id, owner_user_id)
        source = self.snapshot_directory(snapshot.id, project_id)
        payload = self._snapshot_payload(source)
        digests = payload.get("tree_digests")
        if not isinstance(digests, dict):
            raise ValueError("Snapshot digest manifest is invalid")
        self._validate_snapshot_tree(source, digests)
        source_manifest = source / "manifest.json"
        restored_manifest = SessionRecord.model_validate(json.loads(source_manifest.read_text(encoding="utf-8")))
        self._validate_attachment_sources(restored_manifest, source)
        restored = self.workspace.create_session(owner_user_id, project_id)
        try:
            with self.workspace.session_lock(restored.id):
                target = self.workspace.sessions_root / restored.id
                self._copy_snapshot_trees(source, target)
                self._validate_restored_trees(target, digests)
                restored_manifest.id = restored.id
                restored_manifest.created_at = restored.created_at
                restored_manifest.updated_at = datetime.now(timezone.utc)
                restored_manifest.owner_user_id = owner_user_id
                restored_manifest.project_id = project_id
                restored_manifest.restored_from_snapshot_id = snapshot.id
                self.workspace.save_manifest(restored_manifest)
            return ProjectSessionRestoreResult(
                session_id=restored.id,
                snapshot_id=snapshot.id,
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        except Exception:
            self.workspace.delete_session(restored.id)
            raise

    def _require_live_identity(self, session: SessionRecord, project_id: str, owner_user_id: str) -> None:
        if session.project_id != project_id or session.owner_user_id != owner_user_id:
            raise PermissionError("Live session is not available to this owner or project")

    def _copy_live_session(self, session: SessionRecord, destination: Path) -> dict[str, str]:
        source = self.workspace._session_directory(session.id)
        self._reject_reparse_tree(source)
        manifest = source / "manifest.json"
        if not manifest.is_file():
            raise ValueError("Live session manifest is incomplete")
        self._validate_attachment_sources(session, source)
        sanitized = self._sanitized_session(session)
        self._write_json(destination / "manifest.json", sanitized.model_dump(mode="json"))
        self._copy_allowed(source, destination)
        return self._tree_digests(destination)

    @staticmethod
    def _sanitized_session(session: SessionRecord) -> SessionRecord:
        clean = session.model_copy(deep=True)
        clean.messages = []
        for message in session.messages:
            if message.status in {"pending", "streaming"}:
                continue
            safe = message.model_copy(deep=True)
            safe.task_id = None
            safe.reasoning = (
                safe.reasoning.model_copy(update={"entries": [entry for entry in safe.reasoning.entries if entry.provenance == "public_rationale"]})
                if safe.reasoning else None
            )
            if safe.reasoning is not None and not safe.reasoning.entries:
                safe.reasoning = None
            clean.messages.append(safe)
        return clean

    def _validate_attachment_sources(self, session: SessionRecord, source: Path) -> None:
        for attachment in session.attachments:
            content_bearing = attachment.digest is not None or attachment.size > 0
            if content_bearing and (not attachment.storage_name or not _STORAGE_PATTERN.fullmatch(attachment.storage_name)):
                raise ValueError("Live session attachment storage name is invalid")
            if attachment.storage_name and not _STORAGE_PATTERN.fullmatch(attachment.storage_name):
                raise ValueError("Live session attachment storage name is invalid")
            if attachment.storage_name and not self._safe_regular(source / "originals", attachment.storage_name):
                raise ValueError("Live session attachment original is missing")
            if attachment.extraction_state.value == "ready" and (
                not attachment.extracted_name or not _EXTRACTED_PATTERN.fullmatch(attachment.extracted_name)
                or not self._safe_regular(source / "extracted", attachment.extracted_name)
            ):
                raise ValueError("Live session attachment extraction is missing")

    def _safe_regular(self, parent: Path, name: str) -> bool:
        if Path(name).name != name or "/" in name or "\\" in name or name in {"", ".", ".."}:
            return False
        self._check_chain(parent)
        path = parent / name
        self._check_chain(path)
        return path.is_file() and not self._is_reparse_point(path)

    def _copy_snapshot_trees(self, source: Path, destination: Path) -> None:
        self._reject_reparse_tree(source)
        for name in _ALLOWED_TREES:
            tree = source / name
            if tree.exists():
                if not tree.is_dir():
                    raise ValueError("Snapshot tree is invalid")
                shutil.copytree(tree, destination / name, copy_function=shutil.copy2)

    def _copy_allowed(self, source: Path, destination: Path) -> dict[str, str]:
        for name in _ALLOWED_TREES:
            tree = source / name
            if not tree.exists():
                continue
            if not tree.is_dir() or self._is_reparse_point(tree):
                raise ValueError("Session tree is unsafe")
            shutil.copytree(tree, destination / name, copy_function=shutil.copy2)
        return self._tree_digests(destination)

    def _validate_snapshot_tree(self, directory: Path, expected: dict[str, object]) -> None:
        self._reject_reparse_tree(directory)
        actual = self._tree_digests(directory)
        wanted = {str(key): str(value) for key, value in expected.items()}
        if actual != wanted:
            raise ValueError("Snapshot files failed digest validation")

    def _validate_restored_trees(self, directory: Path, expected: dict[str, object]) -> None:
        actual = {key: value for key, value in self._tree_digests(directory).items() if key != "manifest.json"}
        wanted = {str(key): str(value) for key, value in expected.items() if str(key) != "manifest.json"}
        if actual != wanted:
            raise ValueError("Restored files failed digest validation")

    def _tree_digests(self, root: Path) -> dict[str, str]:
        output: dict[str, str] = {}
        for relative in [Path("manifest.json"), *(Path(name) for name in _ALLOWED_TREES)]:
            candidate = root / relative
            if candidate.is_file():
                output[candidate.relative_to(root).as_posix()] = self._digest(candidate)
            elif candidate.exists():
                if not candidate.is_dir():
                    raise ValueError("Snapshot entry is not a regular file or directory")
                for path in sorted(candidate.rglob("*"), key=lambda item: item.as_posix()):
                    if path.is_dir():
                        continue
                    if not path.is_file() or self._is_reparse_point(path):
                        raise ValueError("Snapshot contains an unsafe file")
                    output[path.relative_to(root).as_posix()] = self._digest(path)
        return output

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    def _read_snapshot(self, directory: Path) -> ProjectSessionSnapshot:
        return ProjectSessionSnapshot.model_validate(self._snapshot_payload(directory)["snapshot"])

    @staticmethod
    def _snapshot_payload(directory: Path) -> dict[str, object]:
        path = directory / "snapshot.json"
        if not path.is_file():
            raise ValueError("Snapshot metadata is missing")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Snapshot metadata is invalid")
        return payload

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        ProjectSessionService._write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as destination:
            destination.write(text)
            destination.flush()
            os.fsync(destination.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    def _fsync_tree(self, root: Path) -> None:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                descriptor = os.open(path, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                except OSError:
                    pass
                finally:
                    os.close(descriptor)
            elif path.is_dir():
                self._fsync_directory(path)
        self._fsync_directory(root)

    def _sweep_staging(self, sessions_root: Path) -> None:
        for candidate in sessions_root.iterdir():
            if not _STAGING_PATTERN.fullmatch(candidate.name):
                continue
            if self._is_reparse_point(candidate) or not candidate.is_dir():
                raise ValueError("Snapshot staging entry is unsafe")
            self._reject_reparse_tree(candidate)
            shutil.rmtree(candidate)

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9._/-]+", "-", value.casefold()).strip("-./")[:120]

    def _keywords(
        self,
        session: SessionRecord,
        snapshot_id: str,
        project_id: str,
        title: str,
        change_type: str,
        supplied: list[str],
    ) -> list[str]:
        required = {
            f"snapshot:{snapshot_id}", f"project:{project_id}", f"session:{session.id}", f"change-type:{self._slug(change_type)}",
            f"title:{self._slug(title)}",
        }
        values = set(required)
        for value in supplied:
            raw = str(value).strip()
            namespace, separator, detail = raw.partition(":")
            normalized = (f"{namespace.casefold()}:{self._slug(detail)}" if separator and namespace.casefold() in {"component", "file", "model", "task", "reference"} else self._slug(raw))
            if normalized:
                values.add(normalized)
        for attachment in session.attachments:
            name = self._slug(attachment.display_name)
            if name:
                values.add(f"file:{name}")
        for message in session.messages:
            for model in (message.requested_model, message.effective_model):
                if model and self._slug(model):
                    values.add(f"model:{self._slug(model)}")
            if message.task_id and self._slug(message.task_id):
                values.add(f"task:{self._slug(message.task_id)}")
            for reference in message.references:
                if self._slug(reference.id):
                    values.add(f"reference:{self._slug(reference.id)}")
                if reference.kind == "project_file" and self._slug(reference.label):
                    values.add(f"file:{self._slug(reference.label)}")
                    parts = self._slug(reference.label).split("/")
                    if len(parts) > 1:
                        values.add(f"component:{parts[-2]}")
        optional = sorted(values - required)
        return sorted(required) + optional[:max(0, 128 - len(required))]

    def _summary(self, session: SessionRecord, title: str, change_type: str) -> str:
        lines = [f"Title: {title.strip()}", f"Change type: {change_type.strip()}", f"Created: {session.created_at.isoformat()}"]
        for message in session.messages:
            if message.role == "user":
                lines.append(f"Objective: {message.content[:1200]}")
            elif message.role == "assistant":
                lines.append(f"Outcome ({message.status}): {message.content[:1200]}")
            if message.effective_model or message.requested_model:
                lines.append(f"Model: {message.effective_model or message.requested_model}")
            if message.task_id:
                lines.append(f"Task: {message.task_id}")
            for reference in message.references:
                lines.append(f"Reference: {reference.label}")
        for attachment in session.attachments:
            lines.append(f"Attachment: {attachment.display_name}")
            for warning in attachment.warnings:
                lines.append(f"Warning: {warning}")
        return "\n".join(lines)[:8_000]

    @staticmethod
    def _history_markdown(snapshot: ProjectSessionSnapshot) -> str:
        keywords = ", ".join(snapshot.keywords)
        return f"---\nsnapshot: {snapshot.id}\nkeywords: [{keywords}]\n---\n\n{snapshot.summary}\n"
