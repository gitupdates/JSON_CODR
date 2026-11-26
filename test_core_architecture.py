import re
import unittest
from pathlib import Path

from fastapi import FastAPI

from web_app.core.mutation_inventory import inventory_mutation_routes


class CoreArchitectureTests(unittest.TestCase):
    def test_orchestration_modules_do_not_execute_or_mutate_directly(self):
        forbidden = re.compile(r"\b(subprocess\.|os\.system\(|shutil\.|Path\([^\n]+\)\.(?:write_text|write_bytes|unlink|rename|replace)\()")
        modules = [
            "web_app/core/service.py",
            "web_app/core/agent_runtime.py",
            "web_app/core/delegation.py",
            "web_app/core/scheduler.py",
            "web_app/core/hooks.py",
            "web_app/core/api.py",
            "web_app/core/cli.py",
        ]
        violations = []
        for name in modules:
            for number, line in enumerate(Path(name).read_text(encoding="utf-8").splitlines(), 1):
                if forbidden.search(line):
                    violations.append(f"{name}:{number}:{line.strip()}")
        self.assertEqual(violations, [])

    def test_web_uses_neutral_task_transport_for_execution(self):
        source = Path("web/app.js").read_text(encoding="utf-8") + Path("web/core_client.js").read_text(encoding="utf-8")
        for path in ("/api/chat", "/api/coding-agents", "/api/git-broker/adapter"):
            self.assertNotIn(path, source)
        self.assertIn("/api/tasks", source)

    def test_project_session_mutations_are_inventory_controlled(self):
        application = FastAPI()

        @application.post("/api/projects/resolve")
        async def resolve_project():
            return {}

        @application.post("/api/projects/{project_id}/sessions")
        async def save_session(project_id: str):
            return {"project_id": project_id}

        @application.post("/api/projects/{project_id}/sessions/{snapshot_id}/restore")
        async def restore_session(project_id: str, snapshot_id: str):
            return {"project_id": project_id, "snapshot_id": snapshot_id}

        records = inventory_mutation_routes(application)

        self.assertEqual(
            {(record.method, record.path, record.scope) for record in records},
            {
                ("POST", "/api/projects/resolve", "session.write"),
                ("POST", "/api/projects/{project_id}/sessions", "session.write"),
                ("POST", "/api/projects/{project_id}/sessions/{snapshot_id}/restore", "session.write"),
            },
        )


if __name__ == "__main__":
    unittest.main()
