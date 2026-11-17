from __future__ import annotations

import json
from collections.abc import Iterable
from uuid import uuid7

from web_app.core.contracts import FrozenContract


class ContextSource(FrozenContract):
    kind: str
    source_ref: str
    content: str


class ContextBundle(FrozenContract):
    thread_id: str
    task_id: str
    text: str
    sources: tuple[ContextSource, ...] = ()


class CompactionRecord(FrozenContract):
    compaction_id: str
    thread_id: str
    summary: str
    source_refs: tuple[str, ...] = ()


class ContextService:
    def __init__(self, task_store, memory_store) -> None:
        self._tasks = task_store
        self._memory = memory_store

    def assemble(self, thread_id: str, task_id: str, budget: int) -> ContextBundle:
        sources = list(self._sources(thread_id))
        selected: list[ContextSource] = []
        used = 0
        for source in reversed(sources):
            block_size = len(source.content) + len(source.source_ref) + 8
            if used + block_size > budget:
                continue
            selected.append(source)
            used += block_size
        selected.reverse()
        text = "\n\n".join(f"[{item.source_ref}]\n{item.content}" for item in selected)
        return ContextBundle(thread_id=thread_id, task_id=task_id, text=text, sources=tuple(selected))

    def compact(self, thread_id: str) -> CompactionRecord:
        sources = tuple(self._sources(thread_id))
        summary = "\n".join(item.content for item in sources)
        if len(summary) > 8_000:
            summary = summary[:7_997] + "..."
        return CompactionRecord(
            compaction_id=str(uuid7()),
            thread_id=thread_id,
            summary=summary,
            source_refs=tuple(item.source_ref for item in sources),
        )

    def _sources(self, thread_id: str) -> Iterable[ContextSource]:
        for task in self._tasks.for_thread(thread_id):
            for event in task.events:
                payload = event.model_dump(mode="json")["payload"]
                if payload:
                    yield ContextSource(
                        kind="task_event",
                        source_ref=f"event:{event.event_id}",
                        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    )
        for record in self._memory.list(thread_id):
            yield ContextSource(kind=record.kind, source_ref=record.source_ref, content=record.content)
