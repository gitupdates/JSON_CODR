import subprocess
import tempfile
import unittest
from pathlib import Path

from web_app.core.worktree_runtime import WorktreeRuntime


class WorktreeRuntimeTests(unittest.TestCase):
    def test_git_changes_are_isolated_drift_bound_and_applied_only_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            (root / "app.txt").write_text("before", encoding="utf-8")
            subprocess.run(["git", "add", "app.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            runtime = WorktreeRuntime(Path(directory) / "state")
            session = runtime.create(root)
            try:
                Path(session.working_root, "app.txt").write_text("after", encoding="utf-8")
                self.assertEqual((root / "app.txt").read_text(), "before")
                with self.assertRaisesRegex(RuntimeError, "active writer"):
                    runtime.create(root)
                runtime.apply(session, approved_fingerprint=session.baseline_fingerprint)
                self.assertEqual((root / "app.txt").read_text(), "after")
            finally:
                runtime.close(session)

    def test_dirty_git_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            (root / "dirty.txt").write_text("dirty", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "clean"):
                WorktreeRuntime(Path(directory) / "state").create(root)


if __name__ == "__main__":
    unittest.main()
