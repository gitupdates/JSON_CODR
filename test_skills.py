import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.attachments import AttachmentService
from web_app.skills import SkillConverterService, SkillLibraryService
from web_app.workspace import WorkspaceService


class FakeOllamaService:
    async def health(self): return {"ollama": True}
    async def list_models(self): return []
    async def supports_vision(self, model): return False


def archive(entries: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        for name, content in entries.items():
            bundle.writestr(name, content)
    return output.getvalue()


class SkillLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.workspace = WorkspaceService(self.root)
        self.library = SkillLibraryService(self.root)
        self.converter = SkillConverterService()

    def tearDown(self): self.temporary_directory.cleanup()

    def test_detects_and_converts_claude_codex_and_generic_packs(self):
        fixtures = [
            ("claude.zip", {"pack/.claude-plugin/plugin.json": "{}", "pack/skills/review/SKILL.md": "---\nname: review\ndescription: Review\n---\nClaude tool"}, "claude"),
            ("codex.zip", {"skills/review/SKILL.md": "---\nname: review\ndescription: Review\n---\nCodex skill"}, "codex"),
            ("generic.zip", {"review.md": "# Review\nGeneric instructions"}, "generic"),
        ]
        for filename, entries, expected in fixtures:
            source = self.root / filename
            source.write_bytes(archive(entries))
            pack = self.converter.convert(source, filename)
            self.assertEqual(pack.source_format, expected)
            self.assertTrue(pack.skills)

    def test_translates_provider_specific_skill_syntax(self):
        source = self.root / "claude.zip"
        source.write_bytes(archive({
            "pack/.claude-plugin/plugin.json": "{}",
            "pack/commands/analyze.md": "---\nname: analyze\ntools: Read, Write, Bash\n---\nUse Claude Code. Target: $ARGUMENTS. Call AskUserQuestion then Task(worker).",
        }))

        pack = self.converter.convert(source, source.name)
        content = pack.skills[0].content

        self.assertNotIn("Claude Code", content)
        self.assertNotIn("$ARGUMENTS", content)
        self.assertNotIn("Task(", content)
        self.assertIn("capabilities:", content)
        self.assertIn("{{arguments}}", content)
        self.assertIn("run_role_sequentially(", content)

    def test_converts_7z_skill_pack(self):
        import py7zr

        source_file = self.root / "SKILL.md"
        source_file.write_text("---\nname: seven\ndescription: Seven zip skill\n---\nInstructions", encoding="utf-8")
        source = self.root / "skills.7z"
        with py7zr.SevenZipFile(source, "w") as bundle:
            bundle.write(source_file, "skills/seven/SKILL.md")

        pack = self.converter.convert(source, source.name)

        self.assertEqual(pack.source_format, "codex")
        self.assertEqual(pack.skills[0].name, "seven")

    def test_install_edit_and_remove_preserves_source(self):
        source = self.root / "claude.zip"
        original = archive({"pack/skills/review/SKILL.md": "---\nname: review\ndescription: Review\n---\nOriginal"})
        source.write_bytes(original)
        pack = self.converter.convert(source, source.name)
        installed = self.library.install(pack)
        preserved_source = Path(installed.source_path)
        self.assertTrue(preserved_source.is_file())
        source.unlink()
        skill = installed.skills[0]
        self.library.update_skill(installed.id, skill.id, "Updated instructions", enabled=False)
        changed = self.library.get_skill(installed.id, skill.id)
        self.assertEqual(changed.content, "Updated instructions")
        self.assertFalse(changed.enabled)
        self.assertIn("Original", changed.original_content)
        self.library.remove(installed.id)
        self.assertEqual(self.library.list(), [])
        self.assertEqual(preserved_source.read_bytes(), original)

    def test_api_installs_selects_edits_and_removes_pack(self):
        session = self.workspace.create_session()
        attachments = AttachmentService(self.workspace)
        record = attachments.import_stream(
            session.id,
            "skills.zip",
            io.BytesIO(archive({"skills/review/SKILL.md": "---\nname: review\ndescription: Review code\n---\nDo a careful review."})),
        )
        client = TestClient(create_app(FakeOllamaService(), self.workspace, attachments))
        preview = client.post(f"/api/sessions/{session.id}/attachments/{record.id}/skill-preview")
        self.assertEqual(preview.status_code, 200)
        installed = client.post(f"/api/sessions/{session.id}/attachments/{record.id}/skill-install").json()
        skill_id = installed["skills"][0]["id"]
        selection = f'{installed["id"]}:{skill_id}'
        selected = client.patch(f"/api/sessions/{session.id}/skills", json={"selected": [selection]})
        self.assertEqual(selected.json()["selected_skill_ids"], [selection])
        edited = client.patch(
            f'/api/skills/{installed["id"]}/{skill_id}',
            json={"content": "Updated review instructions", "enabled": True},
        )
        self.assertEqual(edited.json()["content"], "Updated review instructions")
        self.assertEqual(client.delete(f'/api/skills/{installed["id"]}').status_code, 204)
        self.assertEqual(client.get("/api/skills").json(), [])


if __name__ == "__main__": unittest.main()
