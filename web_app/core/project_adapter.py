from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from uuid import uuid7

from pydantic import Field

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext
from web_app.core.contracts import FrozenContract
from web_app.core.project_intelligence import ProjectReader


class ProjectSnapshot(FrozenContract):
    project_root: str
    fingerprint: str
    files: tuple[str, ...]


class CheckpointRecord(FrozenContract):
    checkpoint_id: str
    project_root: str
    target_path: str
    snapshot_path: str
    existed: bool
    digest: str


class ProjectAdapter:
    def __init__(self, state_root: str | Path) -> None:
        self._root = Path(state_root).resolve()
        self._checkpoints = self._root / "checkpoints"
        self._checkpoints.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, CheckpointRecord] = {}
        for manifest in self._checkpoints.glob("*.json"):
            record = CheckpointRecord.model_validate_json(manifest.read_text(encoding="utf-8"))
            self._records[record.checkpoint_id] = record

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        root = self._project_root(call.project_root)
        if call.capability_id == "project.read":
            target = self._target(root, call.target_path, must_exist=True)
            yield AdapterEvent(event_type="project.read", payload={"path": str(target.relative_to(root)), "content": target.read_text(encoding="utf-8", errors="replace")})
            return
        if call.capability_id == "project.search":
            query = str(call.arguments.get("query", ""))
            matches = []
            for path in self._files(root):
                if query in path.read_text(encoding="utf-8", errors="replace"):
                    matches.append(str(path.relative_to(root)))
            yield AdapterEvent(event_type="project.search", payload={"matches": matches})
            return
        if call.capability_id == "checkpoint.create":
            target = self._target(root, call.target_path, must_exist=False)
            record = self.checkpoint(root, target)
            yield AdapterEvent(event_type="checkpoint.created", payload=record.model_dump(mode="json"))
            return
        if call.capability_id == "checkpoint.restore":
            checkpoint_id = str(call.arguments.get("checkpoint_id", ""))
            self.restore(checkpoint_id)
            yield AdapterEvent(event_type="checkpoint.restored", payload={"checkpoint_id": checkpoint_id})
            return
        if call.capability_id == "project.patch":
            target = self._target(root, call.target_path, must_exist=False)
            checkpoint = self.checkpoint(root, target)
            yield AdapterEvent(event_type="checkpoint.created", payload=checkpoint.model_dump(mode="json"))
            content = call.arguments.get("content")
            if not isinstance(content, str):
                raise ValueError("bounded edit requires string content")
            if len(content.encode("utf-8")) > 1_048_576:
                raise ValueError("bounded edit exceeds 1 MiB")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
            yield AdapterEvent(event_type="project.patched", payload={"path": str(target.relative_to(root)), "checkpoint_id": checkpoint.checkpoint_id})
            return
        raise ValueError(f"unsupported project capability: {call.capability_id}")

    def snapshot(self, project_root: str | Path) -> ProjectSnapshot:
        root = self._project_root(project_root)
        files = tuple(str(path.relative_to(root)).replace("\\", "/") for path in self._files(root))
        digest = hashlib.sha256()
        for relative in files:
            digest.update(relative.encode())
            digest.update((root / relative).read_bytes())
        return ProjectSnapshot(project_root=str(root), fingerprint=f"sha256:{digest.hexdigest()}", files=files)

    def checkpoint(self, root: Path, target: Path) -> CheckpointRecord:
        checkpoint_id = str(uuid7())
        destination = self._checkpoints / f"{checkpoint_id}.bin"
        existed = target.is_file()
        content = target.read_bytes() if existed else b""
        destination.write_bytes(content)
        record = CheckpointRecord(
            checkpoint_id=checkpoint_id,
            project_root=str(root),
            target_path=str(target),
            snapshot_path=str(destination),
            existed=existed,
            digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
        )
        self._records[checkpoint_id] = record
        manifest = self._checkpoints / f"{checkpoint_id}.json"
        temporary = manifest.with_suffix(".json.tmp")
        temporary.write_text(record.model_dump_json(), encoding="utf-8")
        temporary.replace(manifest)
        return record

    def restore(self, checkpoint_id: str) -> CheckpointRecord:
        record = self._records.get(checkpoint_id)
        if record is None:
            raise KeyError(checkpoint_id)
        target = Path(record.target_path)
        snapshot = Path(record.snapshot_path)
        if record.existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snapshot, target)
        else:
            target.unlink(missing_ok=True)
        return record

    @staticmethod
    def _project_root(value: str | Path) -> Path:
        root = Path(value).resolve()
        if not root.is_dir():
            raise ValueError("project root must exist")
        return root

    @staticmethod
    def _target(root: Path, value: str | None, *, must_exist: bool) -> Path:
        if value is None:
            raise ValueError("target path is required")
        target = Path(value).resolve()
        if not target.is_relative_to(root):
            raise ValueError("target escapes project root")
        if must_exist and not target.is_file():
            raise FileNotFoundError(target)
        return target

    @staticmethod
    def _files(root: Path) -> tuple[Path, ...]:
        return tuple(root / item.relative_path for item in ProjectReader(root).files())
