import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from web_app.core.adapters import AdapterEvent
from web_app.core.agent_runtime import AgentRuntime
from web_app.core.capabilities import CapabilityRegistry
from web_app.core.context_service import ContextService
from web_app.core.contracts import (
    CapabilityManifest, CompletionCriterion, CriterionKind, CriterionStatus, EvidenceRef,
    GoalSpec, ManifestAuthority, ModelScope, PlanRevision, PlannedStep, TaskCommand,
    TaskPhase, TaskStatus, VerificationReport,
)
from web_app.core.memory import MemoryStore
from web_app.core.plan_service import PlanService
from web_app.core.policy import PolicyService
from web_app.core.service import CoreService
from web_app.core.store import TaskStore
from web_app.models import ExecutionPolicySettings


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    async def execute(self, call, context):
        self.calls.append(call)
        yield AdapterEvent(event_type="capability.result", payload={"operation": call.operation})


class PlanOnce:
    def __init__(self, plan):
        self.plan_value = plan
        self.calls = 0

    async def plan(self, context):
        self.calls += 1
        return self.plan_value


class PassingVerifier:
    async def verify(self, goal, task, context):
        evidence = tuple(EvidenceRef(
            evidence_id=f"evidence-{criterion.criterion_id}", task_id=task.task_id,
            project_id=task.project_id, goal_id=goal.goal_id, goal_revision=goal.revision,
            criterion_id=criterion.criterion_id, source_ref=f"task:{task.task_id}",
            project_fingerprint="sha256:" + "1" * 64, observed_at=datetime.now(UTC),
        ) for criterion in goal.criteria)
        return VerificationReport(
            report_id=f"report-{task.task_id}", task_id=task.task_id, project_id=task.project_id,
            goal_id=goal.goal_id, goal_revision=goal.revision,
            expected_criterion_ids=tuple(item.criterion_id for item in goal.criteria),
            results={item.criterion_id: CriterionStatus.passed for item in goal.criteria},
            evidence=evidence, verified_at=datetime.now(UTC),
        )


def manifest(capability_id):
    return CapabilityManifest(
        capability_id=capability_id, implementation_id=f"{capability_id}.builtin", version="1",
        model_scope=ModelScope.independent, authority=ManifestAuthority.host_builtin,
        manifest_digest="sha256:" + "a" * 64,
    )


class GuidedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tasks = TaskStore(self.root / "tasks.sqlite")
        self.policy = PolicyService(self.root / "policy.sqlite")
        self.memory = MemoryStore(self.root / "memory.sqlite")
        self.registry = CapabilityRegistry()
        for capability in ("project.read", "project.patch", "test.run"):
            self.registry.register(manifest(capability), lambda: object(), lambda _: True)
        self.plans = PlanService(self.tasks, self.registry)
        self.adapter = RecordingAdapter()
        self.core = CoreService(self.tasks, self.policy, {
            "project.read": self.adapter, "project.patch": self.adapter, "test.run": self.adapter,
        })
        self.fingerprint = "sha256:" + "1" * 64

    async def asyncTearDown(self):
        self.memory.close()
        self.policy.close()
        self.tasks.close()
        self.temporary.cleanup()

    def create_task(self):
        task_id = str(uuid7())
        goal = GoalSpec(
            goal_id="goal-1", revision=1, objective="Finish the task", accepted=True,
            criteria=(CompletionCriterion(
                criterion_id="verified", kind=CriterionKind.project_state,
                description="Project is verified",
            ),),
        )
        self.tasks.create(TaskCommand(
            command_id=str(uuid7()), task_id=task_id, thread_id="thread-1", project_id="project-1",
            command_type="agent.run", payload={
                "goal_spec": goal.model_dump(mode="json"), "project_root": str(self.root),
            },
        ))
        return task_id

    def plan(self, task_id):
        return PlanRevision(
            plan_id=f"plan-{task_id}", revision=1, goal_id="goal-1", goal_revision=1,
            summary="Inspect, edit, and test", steps=(
                PlannedStep(
                    step_id="read", plan_id=f"plan-{task_id}", plan_revision=1,
                    criterion_ids=("verified",), capability_id="project.read", operation="read",
                ),
                PlannedStep(
                    step_id="edit", plan_id=f"plan-{task_id}", plan_revision=1,
                    criterion_ids=("verified",), dependencies=("read",),
                    capability_id="project.patch", operation="bounded_edit",
                ),
                PlannedStep(
                    step_id="test", plan_id=f"plan-{task_id}", plan_revision=1,
                    criterion_ids=("verified",), dependencies=("edit",),
                    capability_id="test.run", operation="test",
                ),
            ),
        )

    def runtime(self, task_id, preset):
        snapshot = self.policy.snapshot(ExecutionPolicySettings(preset=preset), "project-1")
        return AgentRuntime(
            self.tasks, self.core, ContextService(self.tasks, self.memory), PlanOnce(self.plan(task_id)),
            PassingVerifier(), lambda _root: self.fingerprint,
            plan_service=self.plans, policy_snapshot=snapshot,
        )

    async def test_every_preset_pauses_for_plan_approval_before_effects(self):
        for preset in ("balanced", "strict", "autonomous"):
            task_id = self.create_task()
            result = await self.runtime(task_id, preset).run(task_id)
            self.assertEqual(self.tasks.phase(task_id), TaskPhase.plan_review)
            self.assertEqual(result.status, TaskStatus.pending)
        self.assertEqual(self.adapter.calls, [])

    async def test_approved_autonomous_plan_executes_steps_then_verifies(self):
        task_id = self.create_task()
        runtime = self.runtime(task_id, "autonomous")
        await runtime.run(task_id)
        plan = self.tasks.plan(task_id, f"plan-{task_id}")
        self.plans.approve_plan(task_id, plan.plan_id, 1, "user", plan.canonical_digest)

        result = await runtime.resume(task_id)

        self.assertEqual(result.status, TaskStatus.completed)
        self.assertEqual([call.capability_id for call in self.adapter.calls], [
            "project.read", "project.patch", "test.run",
        ])
        self.assertEqual(self.tasks.phase(task_id), TaskPhase.completed)

    async def test_changed_project_fingerprint_returns_approved_plan_to_review(self):
        task_id = self.create_task()
        runtime = self.runtime(task_id, "autonomous")
        await runtime.run(task_id)
        plan = self.tasks.plan(task_id, f"plan-{task_id}")
        self.plans.approve_plan(task_id, plan.plan_id, 1, "user", plan.canonical_digest)
        self.fingerprint = "sha256:" + "2" * 64

        result = await runtime.resume(task_id)

        self.assertEqual(self.tasks.phase(task_id), TaskPhase.plan_review)
        self.assertEqual(self.adapter.calls, [])
        self.assertIn("agent.plan_invalidated", [event.event_type for event in result.events])

    async def test_strict_plan_pauses_again_before_first_call(self):
        task_id = self.create_task()
        runtime = self.runtime(task_id, "strict")
        await runtime.run(task_id)
        plan = self.tasks.plan(task_id, f"plan-{task_id}")
        self.plans.approve_plan(task_id, plan.plan_id, 1, "user", plan.canonical_digest)

        result = await runtime.resume(task_id)

        self.assertEqual(self.adapter.calls, [])
        self.assertIn("agent.approval_required", [event.event_type for event in result.events])


if __name__ == "__main__":
    unittest.main()
