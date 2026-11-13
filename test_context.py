import tempfile
import unittest
from pathlib import Path

from web_app.attachments import AttachmentService
from web_app.context import ContextAssembler
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
        from web_app.models import SkillPack, SkillRecord
        from web_app.skills import SkillLibraryService

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


if __name__ == "__main__":
    unittest.main()
