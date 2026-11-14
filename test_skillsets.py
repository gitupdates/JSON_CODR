import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.models import SkillPack, SkillRecord
from web_app.skills import SkillLibraryService
from web_app.skillsets import SkillsetService
from web_app.workspace import WorkspaceService


class FakeService:
    async def health(self): return {"ollama": True}
    async def list_models(self): return []


class SkillsetServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.library = SkillLibraryService(self.root)
        self.library._save([
            SkillPack(
                id="portable",
                name="Portable",
                source_format="codex",
                source_name="portable.zip",
                skills=[
                    SkillRecord(id="python-review", name="Python Review", description="Test and review Python code", content="Review Python tests"),
                    SkillRecord(id="react-ui", name="React UI", description="Build accessible browser UI", content="Build React interfaces"),
                    SkillRecord(id="disabled", name="Cloud Deploy", description="Deploy to cloud", content="Deploy", enabled=False),
                ],
            )
        ])

    def tearDown(self): self.temporary_directory.cleanup()

    def test_reconcile_creates_stable_reference_only_multicategory_skillsets(self):
        service = SkillsetService(self.root, self.library)

        first = service.reconcile()
        second = SkillsetService(self.root, self.library).reconcile()

        self.assertEqual([item.id for item in first], [item.id for item in second])
        by_id = {item.id: item for item in first}
        self.assertIn("coding", by_id)
        self.assertIn("testing-review", by_id)
        self.assertIn("browser-ui", by_id)
        self.assertNotIn("cloud-delivery", by_id)
        self.assertIn("portable:python-review", [member.reference for member in by_id["coding"].members])
        self.assertIn("portable:python-review", [member.reference for member in by_id["testing-review"].members])
        raw = json.loads(service.path.read_text(encoding="utf-8"))
        self.assertNotIn("content", json.dumps(raw).casefold())
        self.assertFalse(any(service.path.parent.glob(".skillsets-*.tmp")))

    def test_reconcile_preserves_user_toggles_and_removes_stale_members(self):
        service = SkillsetService(self.root, self.library)
        service.reconcile()
        raw = json.loads(service.path.read_text(encoding="utf-8"))
        coding = next(item for item in raw if item["id"] == "coding")
        coding["enabled"] = False
        coding["auto_attach"] = False
        service.path.write_text(json.dumps(raw), encoding="utf-8")
        self.library._save([])

        reconciled = service.reconcile()

        self.assertEqual(reconciled, [])
        self.library._save([SkillPack(
            id="replacement", name="Replacement", source_format="codex", source_name="replacement.zip",
            skills=[SkillRecord(id="python", name="Python", description="Python code", content="Code")],
        )])
        restored = {item.id: item for item in service.reconcile()}
        self.assertFalse(restored["coding"].enabled)
        self.assertFalse(restored["coding"].auto_attach)
        self.assertEqual([member.reference for member in restored["coding"].members], ["replacement:python"])

    def test_api_lists_reconciled_skillsets(self):
        client = TestClient(create_app(FakeService(), WorkspaceService(self.root)))

        response = client.get("/api/skillsets")

        self.assertEqual(response.status_code, 200)
        self.assertIn("coding", [item["id"] for item in response.json()])


if __name__ == "__main__": unittest.main()
