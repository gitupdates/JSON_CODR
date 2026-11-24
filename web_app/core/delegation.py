from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from web_app.core.adapters import CapabilityCall
from web_app.core.contracts import TaskCommand, TaskRecord
from web_app.core.resources import ResourceBudget, ResourceSample
from web_app.core.service import CoreService
from web_app.core.store import TaskStore


class DelegationService:
    def __init__(
        self,
        core: CoreService,
        tasks: TaskStore,
        budget: ResourceBudget,
        create_worktree: Callable[[str, str], str | Path] | None = None,
        merge_worktree: Callable[[str], object] | None = None,
    ) -> None:
        self._core = core
        self._tasks = tasks
        self._budget = budget
        self._create_worktree = create_worktree
        self._merge_worktree = merge_worktree

    async def create_child(
        self,
        parent_task_id: str,
        child_task_id: str,
        call: CapabilityCall,
        *,
        allowed_capabilities: Iterable[str],
        sample: ResourceSample,
        editing: bool = False,
    ) -> TaskRecord:
        if call.capability_id not in set(allowed_capabilities):
            raise PermissionError("child capability is outside its delegated tool scope")
        parent = self._tasks.get(parent_task_id)
        child_project_id = parent.project_id
        if editing:
            if self._create_worktree is None:
                raise RuntimeError("editing delegation requires worktree isolation")
            worktree = self._create_worktree(call.project_root, child_task_id)
            child_project_id = self._core.register_delegated_worktree(parent.project_id, worktree)
            call = call.model_copy(update={"project_root": str(worktree)})
        decision = self._budget.evaluate(sample)
        if not decision.allowed:
            call = call.model_copy(update={
                "capability_id": "resource.override",
                "operation": "resource_override",
                "arguments": {**dict(call.arguments), "resource_reason": decision.reason},
            })
        return await self._core.submit(TaskCommand(
            command_id=f"delegate-{child_task_id}",
            task_id=child_task_id,
            thread_id=parent.thread_id,
            project_id=child_project_id if editing else parent.project_id,
            parent_task_id=parent_task_id,
            command_type="delegate.child",
            payload=call.model_dump(mode="json"),
        ))

    def send_input(self, child_task_id: str, user_input: str):
        return self._core.steer(child_task_id, user_input)

    def interrupt(self, child_task_id: str) -> TaskRecord:
        return self._core.cancel(child_task_id)

    def wait(self, child_task_id: str) -> TaskRecord:
        return self._tasks.get(child_task_id)

    def merge_result(self, child_task_id: str):
        if self._merge_worktree is None:
            raise RuntimeError("delegation has no merge boundary")
        self._tasks.get(child_task_id)
        return self._merge_worktree(child_task_id)
