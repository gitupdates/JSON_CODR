from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from web_app.designer.access import DesignPolicyContext, resolve_design_capability
from web_app.designer.contracts import DesignDocument
from web_app.designer.components import ComponentRegistry
from web_app.designer.continuity import validate_runtime_continuity
from web_app.designer.store import DesignerStore, ProjectConflict

if TYPE_CHECKING:
    from web_app.core.identity import AuthenticatedPrincipal, IdentityService


class PublicationRejected(ValueError):
    pass


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    violations: tuple[str, ...] = ()


class PublishedSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: str
    parent_revision_id: str | None = None
    project_id: str
    created_at: datetime
    content_digest: str
    validation: ValidationReport
    document: DesignDocument


class PublicationService:
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(
        self,
        store: DesignerStore,
        *,
        validator: Callable[[DesignDocument], Iterable[str]] | None = None,
        materializer: Callable[[PublishedSnapshot], object] | None = None,
        before_swap: Callable[[str], object] | None = None,
    ) -> None:
        self.store = store
        registry = ComponentRegistry.builtins()
        self.validator = validator or (
            lambda document: tuple(
                violation.message for violation in validate_runtime_continuity(document, registry)
            ) if document.mode == "json_codr" else ()
        )
        self.materializer = materializer or (lambda _snapshot: None)
        self.before_swap = before_swap or (lambda _project_id: None)

    def current(self, project_id: str) -> PublishedSnapshot:
        publication_root = self._publication_root(project_id)
        pointer = self._read_json(publication_root / "current.json")
        if not isinstance(pointer, dict) or set(pointer) != {"revision_id"}:
            raise ValueError("invalid published snapshot pointer")
        revision_id = str(pointer["revision_id"])
        return PublishedSnapshot.model_validate(self._read_json(publication_root / "revisions" / f"{revision_id}.json"))

    def publish(
        self,
        project_id: str,
        draft: DesignDocument,
        expected_revision: str | None,
        context: DesignPolicyContext,
    ) -> PublishedSnapshot:
        decision = resolve_design_capability(context, f"project:{project_id}", "design.publish")
        if not decision.allowed:
            raise PermissionError(decision.reason)
        if draft.project_id != project_id:
            raise ValueError("design belongs to another project")

        with self._lock(project_id):
            current = self._current_or_none(project_id)
            current_revision = current.revision_id if current is not None else None
            if current_revision != expected_revision:
                raise ProjectConflict("expected published revision does not match current snapshot")

            violations = tuple(str(item) for item in self.validator(draft))
            report = ValidationReport(valid=not violations, violations=violations)
            if not report.valid:
                raise PublicationRejected("; ".join(report.violations))

            snapshot = PublishedSnapshot(
                revision_id=f"published-{uuid4().hex}",
                parent_revision_id=current_revision,
                project_id=project_id,
                created_at=datetime.now(timezone.utc),
                content_digest=draft.canonical_digest,
                validation=report,
                document=draft,
            )
            self.materializer(snapshot)
            publication_root = self._publication_root(project_id, create=True)
            revisions = publication_root / "revisions"
            revisions.mkdir(exist_ok=True)
            self._atomic_json(revisions / f"{snapshot.revision_id}.json", snapshot.model_dump(mode="json"))
            self.before_swap(project_id)
            self._atomic_json(publication_root / "current.json", {"revision_id": snapshot.revision_id})
            return snapshot

    def publish_authenticated(
        self,
        project_id: str,
        draft: DesignDocument,
        expected_revision: str | None,
        identity: IdentityService,
        principal: AuthenticatedPrincipal,
    ) -> PublishedSnapshot:
        context = identity.design_policy_context(principal, f"project:{project_id}")
        return self.publish(project_id, draft, expected_revision, context)

    def _current_or_none(self, project_id: str) -> PublishedSnapshot | None:
        pointer = self._publication_root(project_id) / "current.json"
        return self.current(project_id) if pointer.is_file() else None

    def _publication_root(self, project_id: str, *, create: bool = False) -> Path:
        root = self.store.managed_project_path(project_id) / "published"
        if create:
            root.mkdir(exist_ok=True)
        return root

    def _lock(self, project_id: str) -> threading.RLock:
        key = str(self.store.managed_project_path(project_id).resolve())
        with self._locks_guard:
            return self._locks.setdefault(key, threading.RLock())

    @staticmethod
    def _read_json(path: Path) -> object:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
