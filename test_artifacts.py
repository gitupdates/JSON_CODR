import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from web_app.artifacts import ArtifactService
from web_app.attachments import AttachmentService
from web_app.models import GeneratedFile
from web_app.workspace import WorkspaceService


class ArtifactServiceTests(unittest.TestCase):
    def test_saves_generated_files_without_moving_original_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = WorkspaceService(Path(directory))
            session = workspace.create_session()
            attachments = AttachmentService(workspace)
            source = attachments.import_stream(session.id, "claude-skills.zip", io.BytesIO(b"original archive"))
            original_path, _ = attachments.original_path(session.id, source.id)
            artifact = ArtifactService(workspace).save_conversion(
                session.id,
                "claude-skills.zip",
                [
                    GeneratedFile(path="README-CONVERTED.md", content="# Local usage\nRun locally."),
                    GeneratedFile(path="skills/reviewer/SKILL.md", content="# Reviewer\nLocal instructions."),
                ],
            )

            self.assertTrue(original_path.is_file())
            self.assertEqual(original_path.read_bytes(), b"original archive")
            self.assertEqual(artifact.filename, "claude-skills-converted.zip")
            self.assertTrue(Path(artifact.path).is_file())
            with zipfile.ZipFile(artifact.path) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    ["README-CONVERTED.md", "skills/reviewer/SKILL.md"],
                )

    def test_rejects_generated_paths_that_escape_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = WorkspaceService(Path(directory))
            session = workspace.create_session()
            with self.assertRaisesRegex(ValueError, "unsafe"):
                ArtifactService(workspace).save_conversion(
                    session.id,
                    "skills.zip",
                    [GeneratedFile(path="../outside.txt", content="bad")],
                )


if __name__ == "__main__":
    unittest.main()
