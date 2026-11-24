import subprocess
import tempfile
import unittest
from pathlib import Path

from web_app.core.worktree_runtime import RepositoryBusy, WorktreeRuntime


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

    def test_lock_identity_uses_git_common_directory_across_linked_worktrees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            linked = Path(directory) / "linked"
            root.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            (root / "app.txt").write_text("before", encoding="utf-8")
            subprocess.run(["git", "add", "app.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["git", "worktree", "add", "-b", "linked", str(linked)],
                cwd=root, check=True, capture_output=True,
            )
            first = WorktreeRuntime(Path(directory) / "state")
            second = WorktreeRuntime(Path(directory) / "state")
            session = first.create(root, candidate_id="first")
            try:
                with self.assertRaises(RepositoryBusy):
                    second.create(linked, candidate_id="second")
            finally:
                first.close(session)
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(linked)],
                    cwd=root, check=True, capture_output=True,
                )

    def test_commit_verified_requires_commit_tree_to_equal_receipt_tree(self):
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
            session = runtime.create(root, candidate_id="candidate")
            try:
                Path(session.working_root, "app.txt").write_text("after", encoding="utf-8")
                expected_tree = runtime.tree_sha(session)
                with self.assertRaisesRegex(PermissionError, "tree"):
                    runtime.commit_verified(session, "candidate", "0" * 40)
                commit = runtime.commit_verified(session, "candidate", expected_tree)
                actual_tree = subprocess.run(
                    ["git", "rev-parse", f"{commit}^{{tree}}"],
                    cwd=session.working_root, check=True, capture_output=True, text=True,
                ).stdout.strip()
                self.assertEqual(actual_tree, expected_tree)
            finally:
                runtime.close(session)


if __name__ == "__main__":
    unittest.main()
