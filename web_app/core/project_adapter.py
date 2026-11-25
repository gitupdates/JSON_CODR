from __future__ import annotations

import hashlib
import re
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
    applied_digest: str | None = None


class ProjectAdapter:
    MAX_MUTATION_BYTES = 1_048_576

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
            content = call.arguments.get("content")
            if not isinstance(content, str):
                raise ValueError("bounded edit requires string content")
            target = self._target(root, call.target_path, must_exist=False)
            checkpoint = self.atomic_write(root, target, content)
            yield AdapterEvent(event_type="checkpoint.created", payload=checkpoint.model_dump(mode="json"))
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

    def read_lines(
        self,
        project_root: str | Path,
        target_path: str | Path,
        line_range: tuple[int, int] | None,
    ) -> str:
        root = self._project_root(project_root)
        target = self._target(root, target_path, must_exist=True)
        content = target.read_bytes()
        if len(content) > self.MAX_MUTATION_BYTES or b"\x00" in content:
            raise ValueError("native read exceeds 1 MiB or is not UTF-8 text")
        lines = content.decode("utf-8").splitlines()
        start, end = line_range or (1, len(lines))
        if start < 1 or end < start:
            raise ValueError("line range is invalid")
        return "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, min(end, len(lines)) + 1))

    def atomic_write(
        self,
        project_root: str | Path,
        target_path: str | Path,
        content: str,
    ) -> CheckpointRecord:
        encoded = content.encode("utf-8")
        if len(encoded) > self.MAX_MUTATION_BYTES:
            raise ValueError("native write exceeds 1 MiB")
        root = self._project_root(project_root)
        target = self._target(root, target_path, must_exist=False)
        checkpoint = self.checkpoint(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid7()}.tmp")
        try:
            temporary.write_bytes(encoded)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        checkpoint = checkpoint.model_copy(update={
            "applied_digest": f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        })
        self._records[checkpoint.checkpoint_id] = checkpoint
        self._persist_checkpoint(checkpoint)
        return checkpoint

    def apply_edit(
        self,
        project_root: str | Path,
        target_path: str | Path,
        diff_hunk: str,
    ) -> CheckpointRecord:
        if len(diff_hunk.encode("utf-8")) > self.MAX_MUTATION_BYTES:
            raise ValueError("bounded edit exceeds 1 MiB")
        root = self._project_root(project_root)
        target = self._target(root, target_path, must_exist=True)
        original = target.read_text(encoding="utf-8").splitlines()
        updated = self._apply_unified_hunks(original, diff_hunk)
        trailing_newline = target.read_bytes().endswith((b"\n", b"\r"))
        rendered = "\n".join(updated) + ("\n" if trailing_newline else "")
        return self.atomic_write(root, target, rendered)

    @staticmethod
    def _apply_unified_hunks(original: list[str], patch: str) -> list[str]:
        lines = patch.splitlines()
        result: list[str] = []
        source_index = 0
        index = 0
        saw_hunk = False
        while index < len(lines):
            header = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*", lines[index])
            if header is None:
                if lines[index].startswith(("---", "+++")):
                    index += 1
                    continue
                raise ValueError("edit requires a valid unified diff hunk")
            saw_hunk = True
            old_start = int(header.group(1)) - 1
            if old_start < source_index or old_start > len(original):
                raise ValueError("edit hunk position is invalid")
            result.extend(original[source_index:old_start])
            source_index = old_start
            index += 1
            while index < len(lines) and not lines[index].startswith("@@"):
                line = lines[index]
                if not line or line[0] not in {" ", "+", "-"}:
                    raise ValueError("edit hunk contains an invalid line")
                text = line[1:]
                if line[0] in {" ", "-"}:
                    if source_index >= len(original) or original[source_index] != text:
                        raise ValueError("edit context does not match current content")
                    source_index += 1
                if line[0] in {" ", "+"}:
                    result.append(text)
                index += 1
        if not saw_hunk:
            raise ValueError("edit requires a unified diff hunk")
        result.extend(original[source_index:])
        return result

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
        self._persist_checkpoint(record)
        return record

    def _persist_checkpoint(self, record: CheckpointRecord) -> None:
        manifest = self._checkpoints / f"{record.checkpoint_id}.json"
        temporary = manifest.with_suffix(".json.tmp")
        temporary.write_text(record.model_dump_json(), encoding="utf-8")
        temporary.replace(manifest)

    def restore(self, checkpoint_id: str) -> CheckpointRecord:
        record = self._records.get(checkpoint_id)
        if record is None:
            raise KeyError(checkpoint_id)
        target = Path(record.target_path)
        snapshot = Path(record.snapshot_path)
        snapshot_digest = f"sha256:{hashlib.sha256(snapshot.read_bytes()).hexdigest()}"
        if snapshot_digest != record.digest:
            raise PermissionError("checkpoint snapshot digest mismatch")
        if record.applied_digest is not None:
            if not target.is_file():
                raise PermissionError("checkpoint target changed after the approved edit")
            current_digest = f"sha256:{hashlib.sha256(target.read_bytes()).hexdigest()}"
            if current_digest != record.applied_digest:
                raise PermissionError("checkpoint target changed after the approved edit")
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
    def _target(root: Path, value: str | Path | None, *, must_exist: bool) -> Path:
        if value is None:
            raise ValueError("target path is required")
        value_path = Path(value)
        target = (root / value_path).resolve() if not value_path.is_absolute() else value_path.resolve()
        if not target.is_relative_to(root):
            raise ValueError("target escapes project root")
        if must_exist and not target.is_file():
            raise FileNotFoundError(target)
        return target

    @staticmethod
    def _files(root: Path) -> tuple[Path, ...]:
        return tuple(root / item.relative_path for item in ProjectReader(root).files())
