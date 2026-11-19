import os
import tempfile
import unittest
from pathlib import Path

from web_app.core.project_intelligence import ProjectReader, RepositoryIndex, StaleIndex


class ProjectIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        (self.root / "AGENTS.md").write_text("root instruction", encoding="utf-8")
        (self.root / "app.py").write_text("def search_notes(query):\n    return query\n", encoding="utf-8")
        nested = self.root / "src" / "feature"
        nested.mkdir(parents=True)
        (self.root / "src" / "AGENTS.md").write_text("nested instruction", encoding="utf-8")
        (nested / "module.py").write_text("class NotesSearch:\n    pass\n", encoding="utf-8")
        (self.root / "binary.bin").write_bytes(b"\x00\x01\x02")
        ignored = self.root / "node_modules" / "pkg"
        ignored.mkdir(parents=True)
        (ignored / "index.js").write_text("secret ignored", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_reader_skips_ignored_binary_and_symlink_content(self):
        outside = Path(self.temporary.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        symlink = self.root / "outside-link.txt"
        try:
            os.symlink(outside, symlink)
        except OSError:
            symlink = None

        reader = ProjectReader(self.root)
        paths = [item.relative_path for item in reader.files()]

        self.assertIn("app.py", paths)
        self.assertNotIn("binary.bin", paths)
        self.assertFalse(any(path.startswith("node_modules/") for path in paths))
        if symlink is not None:
            self.assertNotIn("outside-link.txt", paths)

    def test_nested_instruction_precedence_is_deterministic(self):
        reader = ProjectReader(self.root)

        instructions = reader.instructions_for("src/feature/module.py")

        self.assertEqual([item.relative_path for item in instructions], ["AGENTS.md", "src/AGENTS.md"])
        self.assertLess(instructions[0].precedence, instructions[1].precedence)
        self.assertEqual(instructions[0].trust, "project")
        self.assertEqual(instructions[1].trust, "scoped_project")

    def test_repository_index_searches_real_content_and_rejects_stale_generation(self):
        reader = ProjectReader(self.root)
        index = RepositoryIndex(Path(self.temporary.name) / "index.sqlite")
        try:
            generation = index.rebuild(reader)
            results = index.search(reader, "NotesSearch")

            self.assertEqual(results[0].relative_path, "src/feature/module.py")
            self.assertEqual(results[0].generation, generation.generation)
            (self.root / "src" / "feature" / "module.py").write_text("class Changed:\n    pass\n", encoding="utf-8")
            with self.assertRaises(StaleIndex):
                index.search(reader, "NotesSearch")
        finally:
            index.close()


if __name__ == "__main__":
    unittest.main()
