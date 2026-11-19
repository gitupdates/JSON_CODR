import io
import tempfile
import unittest
from pathlib import Path
from uuid import uuid7

from test_guided_runtime import PassingVerifier, PlanOnce, RecordingAdapter, manifest
from web_app.core.agent_runtime import AgentRuntime
from web_app.core.agent_verification import build_task_delivery
from web_app.core.artifact_store import ArtifactMetadata, ArtifactStore
from web_app.core.capabilities import CapabilityRegistry
from web_app.core.context_service import ContextService
from web_app.core.contracts import (
    CompletionCriterion, CriterionKind, GoalSpec, PlanRevision, PlannedStep,
    TaskCommand, TaskPhase, TaskStatus,
)
from web_app.core.memory import MemoryStore
from web_app.core.plan_service import PlanService
from web_app.core.policy import PolicyService
from web_app.core.service import CoreService
from web_app.core.store import TaskStore
from web_app.models import ExecutionPolicySettings


class GuidedTaskEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_balanced_task_survives_restart_with_verified_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "tasks.sqlite"
            tasks = TaskStore(database)
            policy = PolicyService(root / "policy.sqlite")
            memory = MemoryStore(root / "memory.sqlite")
            artifacts = ArtifactStore(root / "artifacts", root / "artifacts.sqlite")
            adapter = RecordingAdapter()
            registry = CapabilityRegistry()
            registry.register(manifest("project.read"), lambda: object(), lambda _: True)
            plans = PlanService(tasks, registry)
            task_id = str(uuid7())
            goal = GoalSpec(
                goal_id="goal-1", revision=1, objective="Inspect the project", accepted=True,
                criteria=(CompletionCriterion(
                    criterion_id="verified", kind=CriterionKind.project_state,
                    description="Fresh project evidence exists",
                ),),
            )
            tasks.create(TaskCommand(
                command_id=str(uuid7()), task_id=task_id, thread_id="thread-1",
                project_id="project-1", command_type="agent.run",
                payload={"goal_spec": goal.model_dump(mode="json"), "project_root": str(root)},
            ))
            planned = PlanRevision(
                plan_id=f"plan-{task_id}", revision=1, goal_id="goal-1", goal_revision=1,
                summary="Read project evidence", steps=(PlannedStep(
                    step_id="read", plan_id=f"plan-{task_id}", plan_revision=1,
                    criterion_ids=("verified",), capability_id="project.read", operation="read",
                ),),
            )
            runtime = AgentRuntime(
                tasks, CoreService(tasks, policy, {"project.read": adapter}),
                ContextService(tasks, memory), PlanOnce(planned), PassingVerifier(),
                lambda _root: "sha256:" + "1" * 64,
                plan_service=plans,
                policy_snapshot=policy.snapshot(ExecutionPolicySettings(preset="balanced"), "project-1"),
            )
            try:
                paused = await runtime.run(task_id)
                self.assertEqual(paused.status, TaskStatus.pending)
                self.assertEqual(tasks.phase(task_id), TaskPhase.plan_review)
                current = tasks.plan(task_id, planned.plan_id)
                plans.approve_plan(task_id, planned.plan_id, 1, "user", current.canonical_digest)

                completed = await runtime.resume(task_id)
                self.assertEqual(completed.status, TaskStatus.completed)
                self.assertEqual(len(adapter.calls), 1)
                artifacts.put(io.BytesIO(b"verified"), ArtifactMetadata(
                    task_id=task_id, media_type="text/plain",
                ))
            finally:
                memory.close()
                policy.close()
                tasks.close()

            reopened = TaskStore(database)
            try:
                reconstructed = reopened.get(task_id)
                delivery = build_task_delivery(task_id, reopened, artifacts)
                self.assertEqual(reconstructed.status, TaskStatus.completed)
                self.assertEqual(reopened.phase(task_id), TaskPhase.completed)
                self.assertEqual(delivery.executed_plan_revision, 1)
                self.assertTrue(delivery.verification)
                self.assertEqual(len(delivery.artifacts), 1)
                self.assertNotIn(str(root), delivery.model_dump_json())
            finally:
                reopened.close()
                artifacts.close()


if __name__ == "__main__":
    unittest.main()
