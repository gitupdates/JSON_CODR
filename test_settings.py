import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.models import SettingsUpdate, SkillRoutingSettings, SkillScanSettings, UiSettingsUpdate
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
        self.assertEqual(service.get().version, 2)
        self.assertEqual(service.get().app_version, "V1.0.17-beta.3")
        self.assertTrue(service.get().skill_routing.auto_attach)
        self.assertTrue(service.get().ui.skill_catalog_open)
        self.assertEqual(service.get().ui.theme, "dark")
        service.path.write_text(json.dumps({"version": 1, "future": {"hook": "value"}, "ui": {"future_ui": "kept"}, "skill_scan": {"future_scan": 42}}), encoding="utf-8")
        self.assertEqual(service.get().ui.theme, "dark")

        service.update(SettingsUpdate(
            ui=UiSettingsUpdate(skill_catalog_open=False),
            skill_scan=SkillScanSettings(approved_directories=[str(self.root), str(self.root)]),
            skill_routing=SkillRoutingSettings(auto_attach=False, max_skillsets=2, max_skills=4, minimum_score=9),
        ))

        reloaded = SettingsService(self.root).get()
        self.assertFalse(reloaded.ui.skill_catalog_open)
        self.assertEqual(reloaded.skill_scan.approved_directories, [str(self.root.resolve())])
        self.assertFalse(reloaded.skill_routing.auto_attach)
        self.assertEqual(reloaded.skill_routing.max_skillsets, 2)
        self.assertEqual(json.loads(service.path.read_text(encoding="utf-8"))["future"], {"hook": "value"})
        raw = json.loads(service.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["ui"]["future_ui"], "kept")
        self.assertEqual(raw["skill_scan"]["future_scan"], 42)
        self.assertEqual(raw["version"], 2)

    def test_api_gets_and_updates_settings(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        self.assertEqual(client.get("/api/settings").json()["app_version"], "V1.0.17-beta.3")
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
            "sidebar_collapsed": False,
            "sidebar_width": 260,
            "primary_destination": "chat",
            "hardware_section": "overview",
        })

        second = client.patch("/api/settings", json={"ui": {"theme": "light"}})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["ui"], {
            "skill_catalog_open": False,
            "theme": "light",
            "sidebar_collapsed": False,
            "sidebar_width": 260,
            "primary_destination": "chat",
            "hardware_section": "overview",
        })

    def test_navigation_layout_defaults_and_round_trips_partial_updates(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        self.assertEqual(client.get("/api/settings").json()["ui"], {
            "skill_catalog_open": True,
            "theme": "dark",
            "sidebar_collapsed": False,
            "sidebar_width": 260,
            "primary_destination": "chat",
            "hardware_section": "overview",
        })

        updated = client.patch("/api/settings", json={"ui": {
            "sidebar_collapsed": True,
            "sidebar_width": 340,
            "primary_destination": "hardware",
            "hardware_section": "model-search",
        }})

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["ui"], {
            "skill_catalog_open": True,
            "theme": "dark",
            "sidebar_collapsed": True,
            "sidebar_width": 340,
            "primary_destination": "hardware",
            "hardware_section": "model-search",
        })
        self.assertEqual(SettingsService(self.root).get().ui.model_dump(), updated.json()["ui"])

    def test_legacy_open_skills_migrates_only_without_new_destination(self):
        service = SettingsService(self.root)
        service.path.write_text(json.dumps({"ui": {"skill_catalog_open": True}}), encoding="utf-8")

        self.assertEqual(service.get().ui.primary_destination, "skills")

        service.path.write_text(json.dumps({"ui": {
            "skill_catalog_open": True,
            "primary_destination": "context",
        }}), encoding="utf-8")

        self.assertEqual(service.get().ui.primary_destination, "context")

    def test_navigation_width_is_bounded_and_invalid_destinations_are_rejected(self):
        service = SettingsService(self.root)
        service.path.write_text(json.dumps({"ui": {"sidebar_width": 10}}), encoding="utf-8")
        self.assertEqual(service.get().ui.sidebar_width, 220)
        service.path.write_text(json.dumps({"ui": {"sidebar_width": 999}}), encoding="utf-8")
        self.assertEqual(service.get().ui.sidebar_width, 380)

        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))
        invalid_destination = client.patch("/api/settings", json={"ui": {"primary_destination": "missing"}})
        invalid_section = client.patch("/api/settings", json={"ui": {"hardware_section": "missing"}})

        self.assertEqual(invalid_destination.status_code, 422)
        self.assertEqual(invalid_section.status_code, 422)


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

    def test_leaderboard_is_a_persisted_hardware_section(self):
        client = TestClient(create_app(FakeService(), WorkspaceService(self.root)))
        response = client.patch("/api/settings", json={"ui": {"hardware_section": "leaderboard"}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ui"]["hardware_section"], "leaderboard")

    def test_api_rejects_explicit_null_ui_values(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        for field in (
            "theme", "skill_catalog_open", "sidebar_collapsed", "sidebar_width",
            "primary_destination", "hardware_section",
        ):
            with self.subTest(field=field):
                response = client.patch("/api/settings", json={"ui": {field: None}})
                self.assertEqual(response.status_code, 422)

        current = client.get("/api/settings").json()["ui"]
        self.assertEqual(current, {
            "skill_catalog_open": True,
            "theme": "dark",
            "sidebar_collapsed": False,
            "sidebar_width": 260,
            "primary_destination": "chat",
            "hardware_section": "overview",
        })

    def test_gpu_profiles_default_to_automatic_and_persist_per_model(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        self.assertEqual(client.get("/api/settings").json()["gpu_optimization"], {
            "default_profile": {"mode": "automatic", "num_gpu": None, "main_gpu": None, "num_ctx": None, "num_batch": None},
            "model_profiles": {},
        })
        updated = client.patch("/api/settings", json={
            "gpu_optimization": {
                "default_profile": {"mode": "vram_conservative"},
                "model_profiles": {"qwen2.5-coder:0.5b": {"mode": "gpu_preferred"}},
            },
        })

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["gpu_optimization"]["default_profile"]["mode"], "vram_conservative")
        self.assertEqual(SettingsService(self.root).optimization_for("qwen2.5-coder:0.5b").mode, "gpu_preferred")

    def test_gpu_profile_validation_rejects_unknown_models_and_invalid_advanced_values(self):
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeService(), workspace))

        unknown = client.patch("/api/settings", json={
            "gpu_optimization": {
                "model_profiles": {"missing:model": {"mode": "gpu_preferred"}},
            },
        })
        invalid = client.patch("/api/settings", json={
            "gpu_optimization": {
                "default_profile": {"mode": "advanced", "num_gpu": 2000, "main_gpu": 99},
            },
        })

        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__": unittest.main()
