import json
import tempfile
import unittest
from pathlib import Path

from web_app.core.agent_services import EventEvidenceVerifier, InferencePlanner, ProjectContextResolver
from web_app.core.context_service import ContextBundle, ContextSource
from web_app.core.contracts import CompletionCriterion, CriterionKind, GoalSpec, TaskCommand, TaskEventDraft
from web_app.core.store import TaskStore


class AgentServicesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        (self.root / "app.py").write_text("answer = 42\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def command(self, project_id="project-1", payload=None):
        return TaskCommand(
            command_id="command-1", task_id="task-1", thread_id="thread-1",
            project_id=project_id, command_type="agent.run", payload=payload or {},
        )

    def test_project_resolver_uses_registered_root_and_ignores_payload_root(self):
        attacker = Path(self.temporary.name) / "attacker"
        attacker.mkdir()
        resolver = ProjectContextResolver({"project-1": self.root})

        reader, target = resolver.resolve(self.command(payload={"project_root": str(attacker), "target_path": "app.py"}))

        self.assertEqual(reader.root, self.root.resolve())
        self.assertEqual(target, "app.py")

    def test_project_resolver_rejects_unknown_project(self):
        resolver = ProjectContextResolver({"project-1": self.root})

        with self.assertRaisesRegex(KeyError, "project is not registered"):
            resolver.resolve(self.command(project_id="missing"))

    async def test_planner_validates_model_json_and_overrides_project_root(self):
        async def generate(model, prompt):
            self.assertEqual(model, "local-model")
            self.assertIn("Return one capability call", prompt)
            return json.dumps({
                "capability_id": "project.read", "operation": "read",
                "project_root": "C:/untrusted", "target_path": "app.py",
            })

        planner = InferencePlanner(generate, model="local-model")
        context = ContextBundle(
            thread_id="thread-1", task_id="task-1", text="inspect app.py",
            sources=(ContextSource(
                kind="project_snapshot", source_ref="snapshot", mandatory=True,
                content=json.dumps({"project_root": str(self.root.resolve())}),
            ),),
        )

        call = await planner.plan(context)

        self.assertEqual(call.project_root, str(self.root.resolve()))
        self.assertEqual(call.capability_id, "project.read")

    async def test_planner_returns_none_for_done_and_rejects_invalid_output(self):
        async def done(_model, _prompt):
            return json.dumps({"done": True})

        context = ContextBundle(
            thread_id="thread-1", task_id="task-1", text="done",
            sources=(ContextSource(
                kind="project_snapshot", source_ref="snapshot", mandatory=True,
                content=json.dumps({"project_root": str(self.root.resolve())}),
            ),),
        )
        self.assertIsNone(await InferencePlanner(done, model="local-model").plan(context))

        async def invalid(_model, _prompt):
            return "not-json"

        with self.assertRaisesRegex(ValueError, "valid capability JSON"):
            await InferencePlanner(invalid, model="local-model").plan(context)

    async def test_verifier_uses_persisted_action_evidence_not_model_claims(self):
        store = TaskStore(Path(self.temporary.name) / "tasks.sqlite")
        try:
            command = self.command()
            store.create(command)
            store.append("task-1", TaskEventDraft(event_type="task.started"))
            store.append("task-1", TaskEventDraft(
                event_type="agent.action_completed", payload={"child_task_id": "child-1"},
            ))
            goal = GoalSpec(
                goal_id="goal-1", revision=1, objective="inspect project", accepted=True,
                criteria=(
                    CompletionCriterion(
                        criterion_id="criterion-1", kind=CriterionKind.project_state,
                        description="project action completed",
                    ),
                    CompletionCriterion(
                        criterion_id="artifact-1", kind=CriterionKind.artifact_exists,
                        description="an artifact exists",
                    ),
                    CompletionCriterion(
                        criterion_id="acceptance-1", kind=CriterionKind.user_acceptance,
                        description="the user accepted the result",
                    ),
                ),
            )
            context = ContextBundle(
                thread_id="thread-1", task_id="task-1", text="evidence",
                sources=(ContextSource(
                    kind="project_snapshot", source_ref="snapshot", mandatory=True,
                    content=json.dumps({
                        "project_root": str(self.root.resolve()),
                        "project_fingerprint": "sha256:" + "1" * 64,
                    }),
                ),),
            )

            report = await EventEvidenceVerifier().verify(goal, store.get("task-1"), context)

            self.assertFalse(report.satisfied)
            self.assertEqual(report.results["criterion-1"].value, "passed")
            self.assertEqual(report.results["artifact-1"].value, "failed")
            self.assertEqual(report.results["acceptance-1"].value, "pending")
            self.assertEqual(report.evidence[0].source_ref, "task:task-1:child:child-1")
            self.assertEqual(report.evidence[0].project_fingerprint, "sha256:" + "1" * 64)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
