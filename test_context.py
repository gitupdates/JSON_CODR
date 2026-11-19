import tempfile
import unittest
from pathlib import Path

from web_app.attachments import AttachmentService
from web_app.context import ContextAssembler
from web_app.models import SkillPack, SkillRecommendation, SkillRecommendationResult, SkillRecord
from web_app.skills import SkillLibraryService
from web_app.workspace import WorkspaceService


class ContextAssemblerTests(unittest.TestCase):
    def test_archive_context_is_compact_and_declared_as_already_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = WorkspaceService(Path(directory))
            session = workspace.create_session()
            attachments = AttachmentService(workspace)
            attachments.import_text(session.id, "manifest evidence\n" + ("x" * 80_000), "plugin.zip.txt")

            prompt = ContextAssembler(attachments).build_prompt(
                workspace.get_session(session.id),
                "Review the attached archive",
            )

        self.assertLess(len(prompt), 25_000)
        self.assertIn("already extracted", prompt)
        self.assertIn("manifest evidence", prompt)
        self.assertIn("Analyze the supplied contents directly", prompt)
        self.assertIn("ARCHIVE CONTENTS", prompt)
        self.assertNotIn("BEGIN UNTRUSTED ATTACHMENT", prompt)

    def test_selected_skill_is_injected_in_full(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = WorkspaceService(Path(directory))
            session = workspace.create_session()
            library = SkillLibraryService(Path(directory))
            library.install(SkillPack(id="pack", name="Pack", source_format="generic", source_name="pack.zip", skills=[SkillRecord(id="review", name="Review", content="FULL SKILL INSTRUCTIONS")]))
            session.selected_skill_ids = ["pack:review"]
            workspace.save_manifest(session)
            prompt = ContextAssembler(AttachmentService(workspace), skills=library).build_prompt(session, "Review this")

        self.assertIn("FULL SKILL INSTRUCTIONS", prompt)
        self.assertIn("SELECTED SKILL pack:review", prompt)
        self.assertIn("JSON_CODR_SKILL_SCHEMA: 1", prompt)
        self.assertIn("INTENT:", prompt)
        self.assertIn("EXECUTION_DIRECTIVE:", prompt)
        self.assertIn("Apply every active skill automatically", prompt)

    def test_build_merges_manual_first_deduplicates_and_uses_one_shared_envelope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = WorkspaceService(root)
            session = workspace.create_session()
            library = SkillLibraryService(root)
            library.install(SkillPack(
                id="pack", name="Pack", source_format="generic", source_name="pack.zip",
                skills=[
                    SkillRecord(id="manual", name="Manual", content="MANUAL BODY"),
                    SkillRecord(
                        id="auto", name="Auto", description="Automatic review",
                        content=(
                            "JSON_CODR_SKILL_SCHEMA: 1\nINTENT: repeated\nCAPABILITIES: repeated\n"
                            "SYNTAX: repeated\nEXECUTION_DIRECTIVE: repeated\nAUTO BODY"
                        ),
                    ),
                ],
            ))
            session.selected_skill_ids = ["pack:manual"]
            result = ContextAssembler(AttachmentService(workspace), skills=library).build(
                session,
                "Review this",
                SkillRecommendationResult(recommendations=[
                    SkillRecommendation(reference="pack:auto", name="Auto", score=12, reasons=["name: auto"]),
                    SkillRecommendation(reference="pack:manual", name="Manual", score=1000, reasons=["selected manually"], manual=True),
                ], skillset_ids=["code-review"]),
            )

        self.assertEqual([item.reference for item in result.attached_skills], ["pack:manual", "pack:auto"])
        self.assertEqual(result.skillsets, ["code-review"])
        self.assertLess(result.prompt.index("MANUAL BODY"), result.prompt.index("AUTO BODY"))
        self.assertEqual(result.prompt.count("JSON_CODR_SKILL_SCHEMA: 1"), 1)
        self.assertEqual(result.prompt.count("Apply every active skill automatically"), 1)
        self.assertNotIn("INTENT: repeated", result.prompt)
        self.assertNotIn("EXECUTION_DIRECTIVE: repeated", result.prompt)

    def test_build_skips_stale_and_disabled_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = WorkspaceService(root)
            session = workspace.create_session()
            library = SkillLibraryService(root)
            library.install(SkillPack(
                id="pack", name="Pack", source_format="generic", source_name="pack.zip",
                skills=[SkillRecord(id="disabled", name="Disabled", content="DO NOT ATTACH", enabled=False)],
            ))
            result = ContextAssembler(AttachmentService(workspace), skills=library).build(
                session,
                "Review this",
                SkillRecommendationResult(recommendations=[
                    SkillRecommendation(reference="pack:missing", name="Missing", score=10),
                    SkillRecommendation(reference="pack:disabled", name="Disabled", score=10),
                ]),
            )

        self.assertEqual(result.attached_skills, [])
        self.assertEqual(result.omitted, ["pack:missing", "pack:disabled"])
        self.assertEqual(result.prompt, "Review this")

    def test_skill_budget_omits_whole_skill_and_preserves_full_user_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = WorkspaceService(root)
            session = workspace.create_session()
            library = SkillLibraryService(root)
            library.install(SkillPack(
                id="pack", name="Pack", source_format="generic", source_name="pack.zip",
                skills=[
                    SkillRecord(id="first", name="First", content="A" * 7_000),
                    SkillRecord(id="second", name="Second", content="SECOND-START" + ("B" * 6_900)),
                ],
            ))
            session.selected_skill_ids = ["pack:first"]
            user_prompt = "USER-" + ("request" * 4_000)
            result = ContextAssembler(AttachmentService(workspace), skills=library).build(
                session,
                user_prompt,
                SkillRecommendationResult(recommendations=[
                    SkillRecommendation(reference="pack:first", name="First", score=1000, manual=True),
                    SkillRecommendation(reference="pack:second", name="Second", score=20),
                ]),
            )

        self.assertEqual([item.reference for item in result.attached_skills], ["pack:first"])
        self.assertIn("pack:second", result.omitted)
        self.assertNotIn("SECOND-START", result.prompt)
        self.assertTrue(result.prompt.endswith(user_prompt))
        non_user = result.prompt.rsplit("USER REQUEST:\n", 1)[0]
        self.assertLessEqual(len(non_user), 20_000)

    def test_attachments_receive_at_least_8000_characters_with_shared_ceiling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = WorkspaceService(root)
            session = workspace.create_session()
            attachments = AttachmentService(workspace)
            attachments.import_text(session.id, "ATTACHMENT-BEGIN\n" + ("x" * 30_000), "large.txt")
            session = workspace.get_session(session.id)
            library = SkillLibraryService(root)
            library.install(SkillPack(
                id="pack", name="Pack", source_format="generic", source_name="pack.zip",
                skills=[SkillRecord(id="large", name="Large", content="S" * 11_000)],
            ))
            session.selected_skill_ids = ["pack:large"]
            result = ContextAssembler(attachments, skills=library).build(session, "FULL USER REQUEST")

        self.assertIn("ATTACHMENT-BEGIN", result.prompt)
        self.assertGreaterEqual(result.prompt.count("x"), 8_000)
        non_user = result.prompt.rsplit("USER REQUEST:\n", 1)[0]
        self.assertLessEqual(len(non_user), 20_000)
        self.assertTrue(result.prompt.endswith("FULL USER REQUEST"))


if __name__ == "__main__":
    unittest.main()
