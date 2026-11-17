from __future__ import annotations

from uuid import uuid7

from web_app.core.contracts import TaskCommand, TaskEventDraft, TaskStatus


class AgentRuntime:
    def __init__(self, task_store, core_service, context, planner) -> None:
        self._tasks = task_store
        self._core = core_service
        self.context = context
        self._planner = planner

    async def run(self, task_id: str):
        root = self._tasks.get(task_id)
        if root.status in {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}:
            return root
        if not any(event.event_type == "agent.started" for event in root.events):
            self._tasks.append(task_id, TaskEventDraft(event_type="agent.started"))
        while True:
            root = self._tasks.get(task_id)
            context = self.context.assemble(root.thread_id, task_id, 32_000)
            call = await self._planner.plan(context)
            if call is None:
                self._tasks.append(task_id, TaskEventDraft(event_type="agent.verified"))
                self._tasks.append(task_id, TaskEventDraft(event_type="task.completed"))
                return self._tasks.get(task_id)
            child_id = str(uuid7())
            child = await self._core.submit(TaskCommand(
                command_id=str(uuid7()),
                task_id=child_id,
                thread_id=root.thread_id,
                project_id=root.project_id,
                parent_task_id=task_id,
                command_type=call.capability_id,
                payload=call.model_dump(mode="json"),
            ))
            if child.status is not TaskStatus.completed:
                self._tasks.append(
                    task_id,
                    TaskEventDraft(
                        event_type="task.failed",
                        payload={"reason": "child capability did not complete", "child_task_id": child_id},
                    ),
                )
                return self._tasks.get(task_id)
            self._tasks.append(
                task_id,
                TaskEventDraft(
                    event_type="agent.action_completed",
                    payload={"capability_id": call.capability_id, "child_task_id": child_id},
                ),
            )

    def steer(self, task_id: str, user_input: str):
        return self._tasks.append(task_id, TaskEventDraft(event_type="task.steered", payload={"input": user_input}))

    async def resume(self, task_id: str):
        return await self.run(task_id)
