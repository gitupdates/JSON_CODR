import tempfile
import unittest
from pathlib import Path

from web_app.core.adapters import AdapterEvent, CapabilityCall
from web_app.core.contracts import TaskCommand, TaskStatus
from web_app.core.delegation import DelegationService
from web_app.core.hooks import HookRegistry
from web_app.core.policy import PolicyService
from web_app.core.project_registry import ProjectRegistry
from web_app.core.resources import ResourceBudget, ResourceSample
from web_app.core.scheduler import ScheduleService
from web_app.core.service import CoreService
from web_app.core.store import TaskStore


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    async def execute(self, call, context):
        self.calls.append((call, context))
        yield AdapterEvent(event_type="adapter.output", payload={"task_id": context.task_id})


class AutomationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = TaskStore(self.root / "tasks.sqlite")
        self.policy = PolicyService(self.root / "policy.sqlite")
        self.adapter = RecordingAdapter()
        self.projects = ProjectRegistry(self.root / "projects.sqlite")
        self.projects.register(self.root, project_id="project-1")
        self.core = CoreService(self.store, self.policy, {
            "project.read": self.adapter,
            "project.patch": self.adapter,
            "git.push": self.adapter,
        }, project_roots=self.projects)
        self.parent = TaskCommand(
            command_id="parent-command", task_id="parent-task", thread_id="thread-1",
            project_id="project-1", command_type="parent", payload={
                "capability_id": "project.read", "operation": "read", "project_root": str(self.root),
            },
        )
        await self.core.submit(self.parent)

    async def asyncTearDown(self):
        self.projects.close()
        self.policy.close()
        self.store.close()
        self.temporary.cleanup()

    def call(self, capability="project.read", operation="read"):
        return CapabilityCall(capability_id=capability, operation=operation, project_root=str(self.root))

    async def test_delegation_scopes_tools_isolates_edits_and_attributes_results_once(self):
        worktrees = []
        delegation = DelegationService(
            self.core, self.store, ResourceBudget(max_concurrency=2, max_vram_mb=4096),
            create_worktree=lambda parent, child: worktrees.append((parent, child)) or (self.root / child).mkdir() or self.root / child,
        )

        inspection = await delegation.create_child(
            "parent-task", "child-read", self.call(), allowed_capabilities={"project.read"},
            sample=ResourceSample(active_tasks=0, vram_mb=512),
        )
        editing = await delegation.create_child(
            "parent-task", "child-edit", self.call("project.patch", "replace"),
            allowed_capabilities={"project.patch"}, sample=ResourceSample(active_tasks=1, vram_mb=1024), editing=True,
        )
        repeated = await delegation.create_child(
            "parent-task", "child-read", self.call(), allowed_capabilities={"project.read"},
            sample=ResourceSample(active_tasks=0, vram_mb=512),
        )

        self.assertEqual(inspection.status, TaskStatus.completed)
        self.assertEqual(editing.parent_task_id, "parent-task")
        self.assertEqual(repeated.task_id, inspection.task_id)
        self.assertEqual(len([item for item in self.adapter.calls if item[1].task_id == "child-read"]), 1)
        self.assertEqual(worktrees, [(str(self.root), "child-edit")])
        with self.assertRaises(PermissionError):
            await delegation.create_child(
                "parent-task", "child-denied", self.call("git.push", "push"),
                allowed_capabilities={"project.read"}, sample=ResourceSample(active_tasks=0, vram_mb=0),
            )

    async def test_editing_delegation_registers_a_distinct_worktree_lineage(self):
        worktree = self.root / "child-worktree"

        def create_worktree(_parent, _child):
            worktree.mkdir()
            return worktree

        delegation = DelegationService(
            self.core, self.store, ResourceBudget(max_concurrency=2, max_vram_mb=4096),
            create_worktree=create_worktree,
        )

        record = await delegation.create_child(
            "parent-task", "child-worktree", self.call("project.patch", "replace"),
            allowed_capabilities={"project.patch"},
            sample=ResourceSample(active_tasks=0, vram_mb=0), editing=True,
        )

        command = self.store.command(record.task_id)
        self.assertNotEqual(command.project_id, "project-1")
        registered = self.projects.get(command.project_id)
        self.assertEqual(registered.parent_project_id, "project-1")
        self.assertEqual(registered.root, str(worktree.resolve()))

    async def test_resource_limits_and_schedules_request_permission_without_direct_execution(self):
        delegation = DelegationService(self.core, self.store, ResourceBudget(1, 1024))
        limited = await delegation.create_child(
            "parent-task", "child-limited", self.call(), allowed_capabilities={"project.read"},
            sample=ResourceSample(active_tasks=1, vram_mb=2048),
        )
        self.assertEqual(limited.events[-1].event_type, "task.permission_required")

        schedules = ScheduleService(self.core, project_id="project-1", project_root=str(self.root))
        schedules.create("inspect", self.call())
        schedules.create("publish", self.call("git.push", "push"))
        inspected = await schedules.trigger("inspect", "run-1")
        blocked = await schedules.trigger("publish", "run-1")
        push_call = self.call("git.push", "push").model_copy(update={"schedule_id": "publish"})
        self.policy.grant("user", "project-1", push_call, scope="schedule", schedule_id="publish")
        allowed = await schedules.trigger("publish", "run-2")
        recovered = await schedules.recover_missed("inspect", "missed-1")
        repeated = await schedules.recover_missed("inspect", "missed-1")

        self.assertEqual(inspected.status, TaskStatus.completed)
        self.assertEqual(blocked.events[-1].event_type, "task.permission_required")
        self.assertEqual(allowed.status, TaskStatus.completed)
        self.assertEqual(recovered.task_id, repeated.task_id)
        self.assertEqual(len(schedules.history("inspect")), 2)

    async def test_schedule_registers_optional_trigger_backend_without_delegating_execution(self):
        registrations = []

        class TriggerBackend:
            def add(self, schedule_id, trigger, callback):
                registrations.append((schedule_id, trigger, callback))

        schedules = ScheduleService(
            self.core, project_id="project-1", project_root=str(self.root), trigger_backend=TriggerBackend()
        )
        calls_before = len(self.adapter.calls)
        schedules.create("hourly", self.call(), trigger="cron:0 * * * *")

        self.assertEqual(registrations[0][:2], ("hourly", "cron:0 * * * *"))
        self.assertEqual(len(self.adapter.calls), calls_before)

    async def test_hooks_submit_through_core_and_prevent_recursive_delivery(self):
        hooks = HookRegistry(self.core, project_id="project-1")
        hooks.subscribe("task.completed", "refresh", self.call())

        first = await hooks.publish("task.completed", causation=())
        recursive = await hooks.publish("task.completed", causation=("refresh",))

        self.assertEqual(first[0].status, TaskStatus.completed)
        self.assertEqual(recursive, ())


if __name__ == "__main__":
    unittest.main()
