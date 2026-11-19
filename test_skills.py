import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.attachments import AttachmentService
from web_app.skills import DuplicateSkillPack, SkillConverterService, SkillDiscoveryService, SkillLibraryService
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
    def test_native_json_codr_envelope_is_imported_without_conversion(self):
        source = self.root / "native.zip"
        native = """---
name: native-review
description: Review native JSON_CODR skills
---
--- JSON_CODR SKILL ENVELOPE ---
JSON_CODR_SKILL_SCHEMA: 1
NAME: native-review
INTENT: Review a supplied artifact
CAPABILITIES: read
SYNTAX: Select the skill and provide {{arguments}}.
EXECUTION_DIRECTIVE: Follow the instructions using authorized capabilities only.
--- BEGIN CONVERTED SKILL ---
Review the supplied artifact.
--- END CONVERTED SKILL ---
"""
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("native-review/SKILL.md", native)

        pack = self.converter.convert(source, source.name)

        self.assertEqual(pack.skills[0].content, native.strip())

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

    def test_generic_command_pack_ignores_prompt_helper_markdown(self):
        source = self.root / "commands.zip"
        source.write_bytes(archive({
            "commands/review/review.md": "# Review\nReview code",
            "commands/review/prompt.md": "# Prompt\nInternal prompt helper",
            "commands/deploy/deploy.md": "# Deploy\nDeploy code",
            "commands/deploy/prompt.md": "# Prompt\nDifferent helper",
        }))

        pack = self.converter.convert(source, source.name)

        self.assertEqual([skill.name for skill in pack.skills], ["review", "deploy"])

    def test_deduplicate_removes_normalized_name_collisions_and_keeps_richer_skill(self):
        from web_app.models import SkillPack, SkillRecord
        self.library._save([
            SkillPack(id="one", name="One", source_format="generic", source_name="one.zip", skills=[
                SkillRecord(id="workflow", name="Workflow", description="", content="short"),
            ]),
            SkillPack(id="two", name="Two", source_format="codex", source_name="two.zip", skills=[
                SkillRecord(id="workflow", name=" workflow ", description="Complete workflow", content="much richer workflow instructions"),
            ]),
        ])

        result = self.library.deduplicate()

        remaining = [skill for pack in self.library.list() for skill in pack.skills]
        self.assertEqual(result["removed_skills"], 1)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].description, "Complete workflow")

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

    def test_conversion_persists_standard_json_codr_envelope(self):
        source = self.root / "skill.zip"
        source.write_bytes(archive({"SKILL.md": "---\nname: enveloped\ndescription: Analyze input\ncapabilities: Read, Grep\n---\nAnalyze {{arguments}}"}))

        content = self.converter.convert(source, source.name).skills[0].content

        for field in ("JSON_CODR_SKILL_SCHEMA: 1", "NAME: enveloped", "INTENT: Analyze input", "CAPABILITIES: Read, Grep", "SYNTAX:", "EXECUTION_DIRECTIVE:", "BEGIN CONVERTED SKILL"):
            self.assertIn(field, content)

    def test_existing_catalog_skills_receive_envelope_once(self):
        from web_app.models import SkillPack, SkillRecord
        pack = SkillPack(id="legacy", name="Legacy", source_format="generic", source_name="legacy.zip", skills=[SkillRecord(id="review", name="Review", description="Review code", content="Legacy instructions")])
        self.library._save([pack])

        self.library.ensure_envelopes()
        first = self.library.get_skill("legacy", "review").content
        self.library.ensure_envelopes()
        second = self.library.get_skill("legacy", "review").content

        self.assertIn("JSON_CODR_SKILL_SCHEMA: 1", first)
        self.assertEqual(first, second)

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
        self.assertIn("Updated instructions", changed.content)
        self.assertIn("JSON_CODR_SKILL_SCHEMA: 1", changed.content)
        self.assertFalse(changed.enabled)
        self.assertIn("Original", changed.original_content)
        self.library.remove(installed.id)
        self.assertEqual(self.library.list(), [])
        self.assertEqual(preserved_source.read_bytes(), original)

    def test_prevents_reinstalling_identical_pack(self):
        source = self.root / "claude.zip"
        source.write_bytes(archive({"pack/skills/review/SKILL.md": "---\nname: review\n---\nReview carefully"}))
        self.library.install(self.converter.convert(source, source.name))

        with self.assertRaises(DuplicateSkillPack):
            self.library.install(self.converter.convert(source, source.name))

        self.assertEqual(len(self.library.list()), 1)

    def test_deduplicates_legacy_catalog_by_skill_content(self):
        source = self.root / "claude.zip"
        source.write_bytes(archive({"pack/skills/review/SKILL.md": "---\nname: review\n---\nReview carefully"}))
        pack = self.converter.convert(source, source.name)
        duplicate = pack.model_copy(update={"id": "claude-copy"})
        self.library._save([pack, duplicate])

        result = self.library.deduplicate()

        self.assertEqual(result["removed_packs"], 1)
        self.assertEqual(result["removed_skills"], 1)
        self.assertEqual(len(self.library.list()), 1)

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
        skillsets_path = self.root / "skillsets.json"
        self.assertIn(selection, skillsets_path.read_text(encoding="utf-8"))
        selected = client.patch(f"/api/sessions/{session.id}/skills", json={"selected": [selection]})
        self.assertEqual(selected.json()["selected_skill_ids"], [selection])
        edited = client.patch(
            f'/api/skills/{installed["id"]}/{skill_id}',
            json={"content": "Updated review instructions", "enabled": True},
        )
        self.assertIn("Updated review instructions", edited.json()["content"])
        self.assertIn("JSON_CODR_SKILL_SCHEMA: 1", edited.json()["content"])
        disabled = client.patch(
            f'/api/skills/{installed["id"]}/{skill_id}',
            json={"content": "Updated review instructions", "enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertNotIn(selection, skillsets_path.read_text(encoding="utf-8"))
        self.assertEqual(client.delete(f'/api/skills/{installed["id"]}').status_code, 204)
        self.assertEqual(client.get("/api/skills").json(), [])

    def test_api_save_and_apply_updates_skill_and_selects_it_for_session(self):
        session = self.workspace.create_session()
        attachments = AttachmentService(self.workspace)
        record = attachments.import_stream(
            session.id,
            "skills.zip",
            io.BytesIO(archive({"skills/review/SKILL.md": "---\nname: review\n---\nOriginal instructions"})),
        )
        client = TestClient(create_app(FakeOllamaService(), self.workspace, attachments))
        installed = client.post(
            f"/api/sessions/{session.id}/attachments/{record.id}/skill-install"
        ).json()
        skill_id = installed["skills"][0]["id"]

        saved = client.patch(
            f'/api/skills/{installed["id"]}/{skill_id}',
            json={
                "content": "Updated and applied instructions",
                "enabled": True,
                "session_id": session.id,
            },
        )

        self.assertEqual(saved.status_code, 200)
        self.assertIn("Updated and applied instructions", saved.json()["content"])
        self.assertIn("JSON_CODR_SKILL_SCHEMA: 1", saved.json()["content"])
        selection = f'{installed["id"]}:{skill_id}'
        self.assertEqual(client.get(f"/api/sessions/{session.id}").json()["selected_skill_ids"], [selection])

    def test_api_renames_pack_without_changing_skill_references(self):
        session = self.workspace.create_session()
        attachments = AttachmentService(self.workspace)
        record = attachments.import_stream(
            session.id, "skills.zip", io.BytesIO(archive({"SKILL.md": "---\nname: review\n---\nReview"})),
        )
        client = TestClient(create_app(FakeOllamaService(), self.workspace, attachments))
        installed = client.post(f"/api/sessions/{session.id}/attachments/{record.id}/skill-install").json()

        renamed = client.patch(f'/api/skills/{installed["id"]}', json={"name": "Greenfield Analysis Suite"})

        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["name"], "Greenfield Analysis Suite")
        self.assertEqual(renamed.json()["id"], installed["id"])
        self.assertEqual(renamed.json()["skills"][0]["id"], installed["skills"][0]["id"])

    def test_api_rejects_duplicate_install_and_exposes_cleanup(self):
        session = self.workspace.create_session()
        attachments = AttachmentService(self.workspace)
        record = attachments.import_stream(
            session.id,
            "skills.zip",
            io.BytesIO(archive({"skills/review/SKILL.md": "---\nname: review\n---\nReview carefully"})),
        )
        client = TestClient(create_app(FakeOllamaService(), self.workspace, attachments))
        endpoint = f"/api/sessions/{session.id}/attachments/{record.id}/skill-install"

        self.assertEqual(client.post(endpoint).status_code, 201)
        duplicate = client.post(endpoint)
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("already installed", duplicate.json()["detail"])
        cleanup = client.post("/api/skills/deduplicate")
        self.assertEqual(cleanup.status_code, 200)
        self.assertEqual(cleanup.json()["removed_packs"], 0)

    def test_legacy_skill_documentation_is_complete(self):
        source = self.root / "skills.zip"
        source.write_bytes(archive({"skills/review/SKILL.md": "---\nname: review\ndescription: Reviews code\ncapabilities: Read, Grep\n---\nReview {{arguments}} carefully."}))
        pack = self.library.install(self.converter.convert(source, source.name))

        document = self.library.documentation(pack.id, pack.skills[0].id)

        for heading in ("# review", "## Intent", "## Abilities", "## Command structure and syntax", "## Example use cases", "## Compatibility", "## Instructions"):
            self.assertIn(heading, document)
        self.assertIn("Source pack", document)
        self.assertIn("Original source instructions", document)

    def test_discovery_scans_archive_and_folder_then_revalidates_source(self):
        scan_root = self.root / "scan"
        scan_root.mkdir()
        archive_path = scan_root / "archive.zip"
        archive_path.write_bytes(archive({"skills/archive/SKILL.md": "---\nname: archive\n---\nArchive skill"}))
        folder = scan_root / "folder"
        folder.mkdir()
        (folder / "SKILL.md").write_text("---\nname: folder\n---\nFolder skill", encoding="utf-8")
        discovery = SkillDiscoveryService(self.library, self.converter, self.root)

        result = discovery.scan(scan_root)

        self.assertEqual({item.name for item in result.discoveries}, {"archive", "folder"})
        archive_item = next(item for item in result.discoveries if item.name == "archive")
        archive_path.write_bytes(archive({"skills/archive/SKILL.md": "---\nname: archive\n---\nChanged"}))
        with self.assertRaises(ValueError):
            discovery.install(archive_item.id)

    def test_empty_scan_authorizes_one_known_location_scan(self):
        empty = self.root / "empty"
        empty.mkdir()
        known = self.root / "known"
        known.mkdir()
        (known / "SKILL.md").write_text("---\nname: known\n---\nKnown skill", encoding="utf-8")
        discovery = SkillDiscoveryService(self.library, self.converter, self.root, known_roots=[known])

        result = discovery.scan(empty)
        self.assertIsNotNone(result.fallback_token)
        self.assertEqual(discovery.scan_known(result.fallback_token).discoveries[0].name, "known")
        with self.assertRaises(ValueError):
            discovery.scan_known(result.fallback_token)

    def test_rescan_invalidates_older_discoveries(self):
        first = self.root / "first"; first.mkdir()
        second = self.root / "second"; second.mkdir()
        (first / "SKILL.md").write_text("---\nname: first\n---\nFirst", encoding="utf-8")
        discovery = SkillDiscoveryService(self.library, self.converter, self.root)
        old_id = discovery.scan(first).discoveries[0].id

        discovery.scan(second)

        with self.assertRaises(ValueError):
            discovery.install(old_id)

    def test_scan_rejects_symlink_or_reparse_root(self):
        target = self.root / "target"; target.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Directory symlinks require elevated Windows privileges")
        discovery = SkillDiscoveryService(self.library, self.converter, self.root)
        with self.assertRaises(ValueError):
            discovery.scan(link)

    def test_api_scans_installs_and_downloads_documentation(self):
        scan_root = self.root / "scan"
        scan_root.mkdir()
        (scan_root / "SKILL.md").write_text("---\nname: scanned\ndescription: Scanned skill\n---\nUse it", encoding="utf-8")
        workspace = WorkspaceService(self.root)
        client = TestClient(create_app(FakeOllamaService(), workspace))

        preview = client.post("/api/skills/scan", json={"directory": str(scan_root)})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(client.get("/api/skills").json(), [])
        installed = client.post("/api/skills/install-discovery", json={"discovery_id": preview.json()["discoveries"][0]["id"]})
        self.assertEqual(installed.status_code, 201)
        pack = installed.json()
        document = client.get(f'/api/skills/{pack["id"]}/{pack["skills"][0]["id"]}/documentation.md')
        self.assertEqual(document.status_code, 200)
        self.assertIn("attachment", document.headers["content-disposition"])
        self.assertIn("## Intent", document.text)

        standard = client.get("/api/skills/standard/envelope.md")
        self.assertEqual(standard.status_code, 200)
        self.assertIn("JSON_CODR Skill Envelope Standard", standard.text)
        schema = client.get("/api/skills/standard/envelope.schema.json")
        self.assertEqual(schema.status_code, 200)
        self.assertEqual(schema.json()["properties"]["schema_version"]["const"], 1)


if __name__ == "__main__": unittest.main()
