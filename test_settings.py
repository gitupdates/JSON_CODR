import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.models import SettingsUpdate, SkillScanSettings, UiSettings
from web_app.settings import SettingsService
from web_app.workspace import WorkspaceService


class FakeService:
    async def health(self): return {"ollama": True}
    async def list_models(self): return []


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self): self.temporary_directory.cleanup()

    def test_defaults_and_persistence_preserve_unknown_configuration(self):
        service = SettingsService(self.root)
        self.assertTrue(service.get().ui.skill_catalog_open)
        service.path.write_text(json.dumps({"version": 1, "future": {"hook": "value"}}), encoding="utf-8")

        service.update(SettingsUpdate(
            ui=UiSettings(skill_catalog_open=False),
            skill_scan=SkillScanSettings(approved_directories=[str(self.root), str(self.root)]),
        ))

        reloaded = SettingsService(self.root).get()
        self.assertFalse(reloaded.ui.skill_catalog_open)
        self.assertEqual(reloaded.skill_scan.approved_directories, [str(self.root.resolve())])
        self.assertEqual(json.loads(service.path.read_text(encoding="utf-8"))["future"], {"hook": "value"})

    def test_api_gets_and_updates_settings(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        self.assertTrue(client.get("/api/settings").json()["ui"]["skill_catalog_open"])
        updated = client.patch("/api/settings", json={
            "ui": {"skill_catalog_open": False},
            "skill_scan": {"approved_directories": [str(self.root)]},
        })

        self.assertEqual(updated.status_code, 200)
        self.assertFalse(client.get("/api/settings").json()["ui"]["skill_catalog_open"])


if __name__ == "__main__": unittest.main()
