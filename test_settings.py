import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.models import SettingsUpdate, SkillScanSettings, UiSettingsUpdate
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
        self.assertEqual(service.get().ui.theme, "dark")
        service.path.write_text(json.dumps({"version": 1, "future": {"hook": "value"}, "ui": {"future_ui": "kept"}, "skill_scan": {"future_scan": 42}}), encoding="utf-8")
        self.assertEqual(service.get().ui.theme, "dark")

        service.update(SettingsUpdate(
            ui=UiSettingsUpdate(skill_catalog_open=False),
            skill_scan=SkillScanSettings(approved_directories=[str(self.root), str(self.root)]),
        ))

        reloaded = SettingsService(self.root).get()
        self.assertFalse(reloaded.ui.skill_catalog_open)
        self.assertEqual(reloaded.skill_scan.approved_directories, [str(self.root.resolve())])
        self.assertEqual(json.loads(service.path.read_text(encoding="utf-8"))["future"], {"hook": "value"})
        raw = json.loads(service.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["ui"]["future_ui"], "kept")
        self.assertEqual(raw["skill_scan"]["future_scan"], 42)

    def test_api_gets_and_updates_settings(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        self.assertEqual(client.get("/api/settings").json()["ui"]["theme"], "dark")
        self.assertTrue(client.get("/api/settings").json()["ui"]["skill_catalog_open"])
        updated = client.patch("/api/settings", json={
            "ui": {"skill_catalog_open": False},
            "skill_scan": {"approved_directories": [str(self.root)]},
        })

        self.assertEqual(updated.status_code, 200)
        self.assertFalse(client.get("/api/settings").json()["ui"]["skill_catalog_open"])

    def test_partial_ui_patch_preserves_omitted_sibling_fields(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        first = client.patch("/api/settings", json={
            "ui": {"skill_catalog_open": False},
        })
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["ui"], {
            "skill_catalog_open": False,
            "theme": "dark",
        })

        second = client.patch("/api/settings", json={"ui": {"theme": "light"}})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["ui"], {
            "skill_catalog_open": False,
            "theme": "light",
        })


    def test_api_round_trips_supported_themes(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        for theme in ("light", "dark", "system"):
            updated = client.patch("/api/settings", json={"ui": {"theme": theme}})
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["ui"]["theme"], theme)
            self.assertEqual(client.get("/api/settings").json()["ui"]["theme"], theme)

    def test_api_rejects_unsupported_theme(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        response = client.patch("/api/settings", json={"ui": {"theme": "neon"}})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(client.get("/api/settings").json()["ui"]["theme"], "dark")


if __name__ == "__main__": unittest.main()
