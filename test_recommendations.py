import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.models import AttachmentRecord, ExtractionState, SkillPack, SkillRecord
from web_app.recommendations import SkillRecommendationService
from web_app.settings import SettingsService
from web_app.skills import SkillLibraryService
from web_app.skillsets import SkillsetService
from web_app.workspace import WorkspaceService


class FakeService:
    async def health(self): return {"ollama": True}
    async def list_models(self): return []


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.workspace = WorkspaceService(self.root)
        self.library = SkillLibraryService(self.root)
        self.library._save([SkillPack(
            id="tools", name="Tools", source_format="codex", source_name="tools.zip", skills=[
                SkillRecord(id="python-review", name="Python Review", description="Review quality", content="capabilities: python\nReview code"),
                SkillRecord(id="react-ui", name="React UI", description="Accessible frontend", content="capabilities: browser\nBuild UI"),
                SkillRecord(id="cloud-release", name="Release", description="Cloud delivery", content="capabilities: deploy\nUse Claude provider tools"),
                SkillRecord(id="generic", name="Helper", description="", content="Help with a task"),
            ],
        )])
        self.skillsets = SkillsetService(self.root, self.library)
        self.skillsets.reconcile()
        self.service = SkillRecommendationService(self.library, self.skillsets, SettingsService(self.root))
        self.session = self.workspace.create_session()

    def tearDown(self): self.temporary_directory.cleanup()

    def test_scores_exact_name_capability_category_and_missing_description_weights(self):
        result = self.service.recommend(self.session, "python")

        python = next(item for item in result.recommendations if item.reference == "tools:python-review")
        self.assertEqual(python.score, 17)
        self.assertEqual(python.reasons, ["name: python", "capability: python", "skillset: coding"])
        self.assertNotIn("tools:generic", [item.reference for item in result.recommendations])

    def test_attachment_synonyms_provider_penalty_and_stable_order_are_deterministic(self):
        self.session.attachments.append(AttachmentRecord(
            id="a", display_name="module.py", detected_type="text/x-python", extraction_state=ExtractionState.ready,
        ))

        first = self.service.recommend(self.session, "fix bug in the cloud release")
        second = self.service.recommend(self.session, "fix bug in the cloud release")

        self.assertEqual(first.model_dump(), second.model_dump())
        python = next(item for item in first.recommendations if item.reference == "tools:python-review")
        release = next(item for item in first.recommendations if item.reference == "tools:cloud-release")
        self.assertIn("attachment: .py", python.reasons)
        self.assertIn("provider-only penalty", release.reasons)

    def test_manual_selection_has_priority_and_exclusions_block_automatic_matches(self):
        self.session.selected_skill_ids = ["tools:react-ui"]
        self.session.excluded_skill_ids = ["tools:python-review", "tools:python-review"]

        result = self.service.recommend(self.session, "python")

        self.assertEqual([item.reference for item in result.recommendations], ["tools:react-ui"])
        self.assertTrue(result.recommendations[0].manual)
        self.assertEqual(self.session.excluded_skill_ids, ["tools:python-review"])

    def test_generic_prompt_and_disabled_auto_attach_produce_no_automatic_skills(self):
        self.assertEqual(self.service.recommend(self.session, "help with task").recommendations, [])
        self.session.auto_attach_skills = False
        self.assertEqual(self.service.recommend(self.session, "python").recommendations, [])

    def test_api_previews_reasons_updates_session_controls_and_rejects_unknown_exclusions(self):
        client = TestClient(create_app(FakeService(), self.workspace))

        preview = client.post(f"/api/sessions/{self.session.id}/skill-recommendations", json={"prompt": "python"})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["recommendations"][0]["reference"], "tools:python-review")
        self.assertTrue(preview.json()["recommendations"][0]["reasons"])

        updated = client.patch(f"/api/sessions/{self.session.id}/skill-routing", json={
            "auto_attach_skills": False,
            "excluded_skill_ids": ["tools:python-review", "tools:python-review"],
        })
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["auto_attach_skills"])
        self.assertEqual(updated.json()["excluded_skill_ids"], ["tools:python-review"])

        rejected = client.patch(f"/api/sessions/{self.session.id}/skill-routing", json={
            "excluded_skill_ids": ["missing:skill"],
        })
        self.assertEqual(rejected.status_code, 422)

    def test_recommendations_recalculate_after_skill_pack_removal(self):
        client = TestClient(create_app(FakeService(), self.workspace))
        self.assertTrue(client.post(f"/api/sessions/{self.session.id}/skill-recommendations", json={"prompt": "python"}).json()["recommendations"])

        self.assertEqual(client.delete("/api/skills/tools").status_code, 204)

        self.assertEqual(client.post(f"/api/sessions/{self.session.id}/skill-recommendations", json={"prompt": "python"}).json()["recommendations"], [])


if __name__ == "__main__": unittest.main()
