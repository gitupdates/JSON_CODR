from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from web_app.core.canonical import canonical_digest
from web_app.designer.contracts import DesignDocument
from web_app.designer.templates import create_template


_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class ProjectConflict(RuntimeError):
    """Raised when a write was based on stale project state."""


class ProjectRevision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: str
    parent_revision_id: str | None = None
    created_at: datetime
    content_digest: str
    document: DesignDocument


class DesignerStore:
    """Atomic, revisioned storage for structured Designer projects."""

    def __init__(
        self,
        data_root: str | Path,
        *,
        replace_file: Callable[[str | Path, str | Path], object] = os.replace,
    ) -> None:
        self.projects_root = Path(data_root) / "designer" / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self._replace_file = replace_file

    def create_project(self, template_id: str, name: str) -> DesignDocument:
        document = create_template(template_id, name)
        self._initialize_project(document)
        return document

    def managed_project_path(self, project_id: str) -> Path:
        """Return a validated existing project directory for colocated services."""
        return self._project_dir(project_id, must_exist=True)

    def get_project(self, project_id: str) -> DesignDocument:
        manifest = self._manifest(project_id)
        return self._revision(project_id, manifest["current_revision_id"]).document

    def list_revisions(self, project_id: str) -> tuple[ProjectRevision, ...]:
        manifest = self._manifest(project_id)
        current_id: str | None = manifest["current_revision_id"]
        newest_first: list[ProjectRevision] = []
        seen: set[str] = set()
        while current_id is not None:
            if current_id in seen:
                raise ValueError("revision history contains a cycle")
            seen.add(current_id)
            current = self._revision(project_id, current_id)
            newest_first.append(current)
            current_id = current.parent_revision_id
        return tuple(reversed(newest_first))

    def save_revision(
        self,
        project_id: str,
        document: DesignDocument,
        expected_digest: str,
    ) -> ProjectRevision:
        project = self._project_dir(project_id, must_exist=True)
        self._require_document_owner(project_id, document)
        manifest = self._manifest(project_id)
        self._require_current_digest(manifest, expected_digest)
        revision = self._new_revision(document, manifest["current_revision_id"])
        self._atomic_json(project / "revisions" / f"{revision.revision_id}.json", revision.model_dump(mode="json"))
        self._atomic_json(project / "manifest.json", self._manifest_for(revision))
        draft = project / "draft.json"
        if draft.exists():
            draft.unlink()
        return revision

    def save_draft(
        self,
        project_id: str,
        document: DesignDocument,
        expected_digest: str,
    ) -> DesignDocument:
        project = self._project_dir(project_id, must_exist=True)
        self._require_document_owner(project_id, document)
        self._require_current_digest(self._manifest(project_id), expected_digest)
        self._atomic_json(project / "draft.json", document.model_dump(mode="json"))
        return document

    def get_draft(self, project_id: str) -> DesignDocument | None:
        path = self._project_dir(project_id, must_exist=True) / "draft.json"
        if not path.exists():
            return None
        return DesignDocument.model_validate(self._read_json(path))

    def restore_revision(
        self,
        project_id: str,
        revision_id: str,
        expected_digest: str,
    ) -> ProjectRevision:
        historical = self._revision(project_id, revision_id)
        return self.save_revision(project_id, historical.document, expected_digest)

    def duplicate_project(self, project_id: str, name: str) -> DesignDocument:
        source = self.get_project(project_id)
        payload = source.model_dump(mode="json", exclude={"canonical_digest"})
        payload["project_id"] = f"design-{uuid4().hex}"
        payload["name"] = name
        payload["metadata"] = {**payload.get("metadata", {}), "duplicated_from": project_id}
        duplicate = DesignDocument.model_validate(payload)
        self._initialize_project(duplicate)
        return duplicate

    def deletion_token(self, project_id: str) -> str:
        manifest = self._manifest(project_id)
        return canonical_digest({
            "operation": "delete-designer-project",
            "project_id": project_id,
            "revision_id": manifest["current_revision_id"],
            "content_digest": manifest["current_digest"],
        })

    def delete_project(self, project_id: str, confirmation_token: str) -> None:
        expected = self.deletion_token(project_id)
        if not hmac.compare_digest(expected, confirmation_token):
            raise ProjectConflict("confirmation token does not match current project state")
        project = self._project_dir(project_id, must_exist=True)
        if project.resolve().parent != self.projects_root.resolve():
            raise ValueError("project path escapes the managed root")
        shutil.rmtree(project)

    def _initialize_project(self, document: DesignDocument) -> None:
        project = self._project_dir(document.project_id)
        project.mkdir()
        (project / "revisions").mkdir()
        revision = self._new_revision(document, None)
        try:
            self._atomic_json(project / "revisions" / f"{revision.revision_id}.json", revision.model_dump(mode="json"))
            self._atomic_json(project / "manifest.json", self._manifest_for(revision))
        except BaseException:
            shutil.rmtree(project, ignore_errors=True)
            raise

    def _new_revision(self, document: DesignDocument, parent_id: str | None) -> ProjectRevision:
        return ProjectRevision(
            revision_id=f"revision-{uuid4().hex}",
            parent_revision_id=parent_id,
            created_at=datetime.now(timezone.utc),
            content_digest=document.canonical_digest,
            document=document,
        )

    @staticmethod
    def _manifest_for(revision: ProjectRevision) -> dict[str, str]:
        return {
            "current_revision_id": revision.revision_id,
            "current_digest": revision.content_digest,
        }

    def _manifest(self, project_id: str) -> dict[str, str]:
        path = self._project_dir(project_id, must_exist=True) / "manifest.json"
        value = self._read_json(path)
        if not isinstance(value, dict):
            raise ValueError("invalid project manifest")
        return value

    def _revision(self, project_id: str, revision_id: str) -> ProjectRevision:
        if not _PROJECT_ID.fullmatch(revision_id):
            raise ValueError("invalid revision identifier")
        path = self._project_dir(project_id, must_exist=True) / "revisions" / f"{revision_id}.json"
        if not path.is_file():
            raise KeyError(revision_id)
        return ProjectRevision.model_validate(self._read_json(path))

    def _project_dir(self, project_id: str, *, must_exist: bool = False) -> Path:
        if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
            raise ValueError("invalid project identifier")
        path = self.projects_root / project_id
        if path.resolve().parent != self.projects_root.resolve():
            raise ValueError("project path escapes the managed root")
        if must_exist and not path.is_dir():
            raise KeyError(project_id)
        return path

    @staticmethod
    def _require_document_owner(project_id: str, document: DesignDocument) -> None:
        if document.project_id != project_id:
            raise ValueError("design belongs to another project")

    @staticmethod
    def _require_current_digest(manifest: dict[str, str], expected_digest: str) -> None:
        if not hmac.compare_digest(manifest["current_digest"], expected_digest):
            raise ProjectConflict("expected current digest does not match stored current digest")

    @staticmethod
    def _read_json(path: Path) -> object:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)

    def _atomic_json(self, path: Path, value: object) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._replace_file(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
