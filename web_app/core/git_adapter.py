from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from web_app.core.adapters import AdapterEvent, CapabilityCall, ExecutionContext
from web_app.core.contracts import FrozenContract, TaskId
from web_app.models import BrokerActionRequest


class WorktreeRecord(FrozenContract):
    task_id: TaskId
    repository_root: str
    worktree_root: str
    branch: str
    base_commit: str


class MergeEvidence(FrozenContract):
    task_id: TaskId
    branch: str
    commit: str
    output: str


class GitAdapter:
    def __init__(self, broker) -> None:
        self._broker = broker

    def create_worktree(
        self, repository_root: str | Path, worktree_root: str | Path, branch: str, task_id: str
    ) -> WorktreeRecord:
        values = self._broker.create_worktree(repository_root, worktree_root, branch)
        return WorktreeRecord(
            task_id=task_id,
            **values,
        )

    def merge_worktree(self, repository_root: str | Path, record: WorktreeRecord) -> MergeEvidence:
        values = self._broker.merge_worktree_branch(repository_root, record.branch)
        return MergeEvidence(task_id=record.task_id, **values)


class GitExecutionAdapter:
    def __init__(self, broker, authorized) -> None:
        self._broker = broker
        self._authorized = authorized

    async def execute(self, call: CapabilityCall, context: ExecutionContext):
        request_value = call.arguments.get("request")
        if not isinstance(request_value, Mapping):
            raise ValueError("git execution requires a broker request")
        request = BrokerActionRequest.model_validate(dict(request_value))
        model = call.arguments.get("model")
        grant_id = call.arguments.get("grant_id")
        if not isinstance(model, str) or not isinstance(grant_id, str):
            raise ValueError("git execution requires model and grant identity")

        def authorized() -> bool:
            return bool(self._authorized(grant_id, request.project_root))

        if not authorized():
            raise PermissionError("broker authorization does not cover this project")
        result = await asyncio.to_thread(self._broker.execute, request, model, grant_id, authorized)
        yield AdapterEvent(event_type="git.completed", payload={"result": asdict(result)})
