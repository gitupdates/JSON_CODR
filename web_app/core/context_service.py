from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import uuid7

from web_app.core.canonical import canonical_digest
from web_app.core.contracts import FrozenContract
from web_app.core.project_intelligence import ProjectFile, ProjectInstruction, ProjectReader


class ContextSource(FrozenContract):
    kind: str
    source_ref: str
    content: str
    event_type: str | None = None
    global_sequence: int | None = None
    mandatory: bool = False


class ContextBundle(FrozenContract):
    thread_id: str
    task_id: str
    text: str
    sources: tuple[ContextSource, ...] = ()


class CompactionRecord(FrozenContract):
    compaction_id: str
    thread_id: str
    summary: str
    through_global_sequence: int
    source_refs: tuple[str, ...] = ()
    mandatory_sources: tuple[ContextSource, ...] = ()
    created_at: datetime


class ProjectContextSnapshot(FrozenContract):
    snapshot_id: str
    thread_id: str
    task_id: str
    project_root: str
    project_fingerprint: str
    target_path: str
    through_global_sequence: int
    instructions: tuple[ProjectInstruction, ...] = ()
    files: tuple[ProjectFile, ...] = ()


class ContextOverflow(RuntimeError):
    pass


class ContextService:
    def __init__(self, task_store, memory_store) -> None:
        self._tasks = task_store
        self._memory = memory_store

    def assemble(self, thread_id: str, task_id: str, budget: int) -> ContextBundle:
        sources = list(self._sources(thread_id))
        required = [source for source in sources if source.mandatory]
        required_size = sum(self._block_size(source) for source in required)
        if required_size > budget:
            raise ContextOverflow(
                f"mandatory context requires {required_size} characters but budget is {budget}"
            )
        selected_refs = {source.source_ref for source in required}
        selected = list(required)
        used = required_size
        for source in reversed(sources):
            if source.source_ref in selected_refs:
                continue
            block_size = self._block_size(source)
            if used + block_size > budget:
                continue
            selected.append(source)
            selected_refs.add(source.source_ref)
            used += block_size
        source_positions = {source.source_ref: index for index, source in enumerate(sources)}
        selected.sort(key=lambda source: source_positions[source.source_ref])
        text = "\n\n".join(f"[{item.source_ref}]\n{item.content}" for item in selected)
        return ContextBundle(thread_id=thread_id, task_id=task_id, text=text, sources=tuple(selected))

    def compact(self, thread_id: str) -> CompactionRecord:
        sources = tuple(self._sources(thread_id))
        mandatory_sources = tuple(item for item in sources if item.mandatory)
        optional_sources = tuple(item for item in sources if not item.mandatory and item.kind != "context_compaction")
        summary = "\n".join(f"[{item.source_ref}] {item.content}" for item in optional_sources)
        if len(summary) > 8_000:
            summary = summary[:7_997] + "..."
        prior = self._latest_compaction(thread_id)
        source_refs = [] if prior is None else list(prior.source_refs)
        source_refs.extend(
            source.source_ref for source in sources
            if source.kind != "context_compaction" and source.source_ref not in source_refs
        )
        through = max(
            (source.global_sequence for source in sources if source.global_sequence is not None),
            default=-1 if prior is None else prior.through_global_sequence,
        )
        record = CompactionRecord(
            compaction_id=str(uuid7()),
            thread_id=thread_id,
            summary=summary,
            through_global_sequence=through,
            source_refs=tuple(source_refs),
            mandatory_sources=mandatory_sources,
            created_at=datetime.now(UTC),
        )
        self._memory.add(
            thread_id,
            "context_compaction",
            record.model_dump_json(),
            source_ref=f"compaction:{record.compaction_id}",
        )
        return record

    def capture_project(
        self,
        thread_id: str,
        task_id: str,
        reader: ProjectReader,
        *,
        target_path: str = ".",
    ) -> ProjectContextSnapshot:
        events = self._tasks.thread_events(thread_id)
        through = max((event.global_sequence for event in events), default=-1)
        instructions = reader.instructions_for(target_path)
        files = reader.files()
        instruction_paths = {item.relative_path for item in instructions}
        files = tuple(item for item in files if item.relative_path not in instruction_paths)
        material = {
            "thread_id": thread_id,
            "task_id": task_id,
            "project_root": str(reader.root),
            "project_fingerprint": reader.fingerprint(files),
            "target_path": target_path,
            "instructions": [item.model_dump(mode="json") for item in instructions],
            "files": [
                {"relative_path": item.relative_path, "digest": item.digest, "size": item.size}
                for item in files
            ],
        }
        snapshot_id = canonical_digest(material)
        for record in self._memory.list(thread_id):
            if record.kind != "project_context_snapshot":
                continue
            existing = ProjectContextSnapshot.model_validate_json(record.content)
            if existing.snapshot_id == snapshot_id:
                return existing
        snapshot = ProjectContextSnapshot(
            snapshot_id=snapshot_id,
            thread_id=thread_id,
            task_id=task_id,
            project_root=str(reader.root),
            project_fingerprint=material["project_fingerprint"],
            target_path=target_path,
            through_global_sequence=through,
            instructions=instructions,
            files=files,
        )
        self._memory.replace_kind(
            thread_id,
            "project_context_snapshot",
            snapshot.model_dump_json(),
            source_ref=f"project-snapshot:{snapshot.snapshot_id}",
        )
        return snapshot

    def _sources(self, thread_id: str) -> Iterable[ContextSource]:
        compaction = self._latest_compaction(thread_id)
        compacted_refs = set() if compaction is None else set(compaction.source_refs)
        if compaction is not None:
            yield ContextSource(
                kind="context_compaction",
                source_ref=f"compaction:{compaction.compaction_id}",
                content=compaction.summary,
                global_sequence=compaction.through_global_sequence,
                mandatory=True,
            )
            yield from compaction.mandatory_sources
        cursor = -1 if compaction is None else compaction.through_global_sequence
        for event in self._tasks.thread_events(thread_id, cursor):
            payload = event.model_dump(mode="json")["payload"]
            if payload:
                yield ContextSource(
                    kind="task_event",
                    source_ref=f"event:{event.event_id}",
                    content=json.dumps(
                        {"event_type": event.event_type, "payload": payload},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    event_type=event.event_type,
                    global_sequence=event.global_sequence,
                    mandatory=event.event_type in {
                        "agent.goal_registered",
                        "agent.verification_failed",
                        "task.steered",
                    },
                )
        for record in self._memory.list(thread_id):
            if record.kind == "context_compaction" or record.source_ref in compacted_refs:
                continue
            if record.kind == "project_context_snapshot":
                snapshot = ProjectContextSnapshot.model_validate_json(record.content)
                snapshot_ref = f"project-snapshot:{snapshot.snapshot_id}"
                if snapshot_ref not in compacted_refs:
                    yield ContextSource(
                        kind="project_snapshot",
                        source_ref=snapshot_ref,
                        content=json.dumps(
                            {
                                "project_root": snapshot.project_root,
                                "project_fingerprint": snapshot.project_fingerprint,
                                "through_global_sequence": snapshot.through_global_sequence,
                            },
                            sort_keys=True,
                        ),
                        global_sequence=snapshot.through_global_sequence,
                        mandatory=True,
                    )
                for instruction in snapshot.instructions:
                    source_ref = f"{snapshot_ref}:instruction:{instruction.relative_path}"
                    if source_ref not in compacted_refs:
                        yield ContextSource(
                            kind="project_instruction",
                            source_ref=source_ref,
                            content=instruction.content,
                            global_sequence=snapshot.through_global_sequence,
                            mandatory=True,
                        )
                for project_file in snapshot.files:
                    source_ref = f"{snapshot_ref}:file:{project_file.relative_path}"
                    if source_ref not in compacted_refs:
                        yield ContextSource(
                            kind="project_file",
                            source_ref=source_ref,
                            content=project_file.content,
                            global_sequence=snapshot.through_global_sequence,
                        )
                continue
            yield ContextSource(kind=record.kind, source_ref=record.source_ref, content=record.content)

    def _latest_compaction(self, thread_id: str) -> CompactionRecord | None:
        records = [
            record for record in self._memory.list(thread_id) if record.kind == "context_compaction"
        ]
        if not records:
            return None
        return CompactionRecord.model_validate_json(records[-1].content)

    @staticmethod
    def _block_size(source: ContextSource) -> int:
        return len(source.content) + len(source.source_ref) + 8
