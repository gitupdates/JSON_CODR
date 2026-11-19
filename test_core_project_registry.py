import os
import tempfile
import unittest
from pathlib import Path

from web_app.core.project_registry import ProjectRegistry


class ProjectRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.database = self.base / "projects.sqlite"

    def tearDown(self):
        self.temporary.cleanup()

    def test_registration_is_stable_durable_and_scoped_per_project(self):
        first = ProjectRegistry(self.database)
        one = first.register(self.root)
        self.assertEqual(first.register(self.root).project_id, one.project_id)
        first.close()

        second = ProjectRegistry(self.database)
        try:
            self.assertEqual(second.resolve(one.project_id), self.root.resolve())
            other_root = self.base / "other"
            other_root.mkdir()
            other = second.register(other_root)
            self.assertNotEqual(one.project_id, other.project_id)
            self.assertEqual({item.project_id for item in second.list()}, {one.project_id, other.project_id})
        finally:
            second.close()

    def test_unknown_missing_and_replaced_roots_are_rejected(self):
        registry = ProjectRegistry(self.database)
        record = registry.register(self.root)
        with self.assertRaisesRegex(KeyError, "not registered"):
            registry.resolve("project:missing")
        self.root.rename(self.base / "moved")
        with self.assertRaisesRegex(ValueError, "missing"):
            registry.resolve(record.project_id)
        self.root.mkdir()
        with self.assertRaisesRegex(ValueError, "identity changed"):
            registry.resolve(record.project_id)
        registry.close()

    def test_symlink_or_reparse_root_is_rejected(self):
        link = self.base / "linked"
        try:
            os.symlink(self.root, link, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlinks are unavailable")
        registry = ProjectRegistry(self.database)
        try:
            with self.assertRaisesRegex(ValueError, "link or reparse"):
                registry.register(link)
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
