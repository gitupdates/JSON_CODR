import os
import gc
import subprocess
import tempfile
import unittest
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path

from web_app.core.worktree_runtime import RepositoryBusy, WorktreeRuntime


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return result.stdout.strip()


def repository(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    git(project, "init", "-b", "main")
    git(project, "config", "user.name", "JSON CODR Tests")
    git(project, "config", "user.email", "tests@example.invalid")
    (project / "README.md").write_text("initial\n", encoding="utf-8")
    git(project, "add", "README.md")
    git(project, "commit", "-m", "initial")
    return project


class WorktreeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = repository(self.root)
        self.runtime = WorktreeRuntime(self.root / "state")

    def tearDown(self):
        self.temporary.cleanup()

    def test_dirty_source_is_rejected_before_a_candidate_is_created(self):
        """Removing the tracked/untracked cleanliness guard must fail this test."""
        (self.project / "UNTRACKED.txt").write_text("not approved\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "clean source"):
            self.runtime.create(self.project, candidate_id="candidate-dirty")

        self.assertEqual(list((self.root / "state" / "worktrees").glob("*")), [])

    def test_repository_lock_is_visible_to_another_runtime(self):
        """Replacing the OS lock with a process-local mutex must fail this test."""
        first = self.runtime.create(self.project, candidate_id="candidate-one")
        other = WorktreeRuntime(self.root / "state")
        try:
            with self.assertRaises(RepositoryBusy) as raised:
                other.create(self.project, candidate_id="candidate-two")
            self.assertEqual(raised.exception.owner.candidate_id, "candidate-one")
            self.assertEqual(raised.exception.owner.owner_pid, os.getpid())
        finally:
            self.runtime.close(first)

    def test_expired_lock_is_recovered_only_after_verified_owner_death(self):
        """Expiry alone must never let a second writer steal a live repository lock."""
        now = datetime(2026, 11, 24, tzinfo=UTC)
        alive = {os.getpid(): True}
        first_runtime = WorktreeRuntime(
            self.root / "state", lock_ttl=timedelta(seconds=1),
            clock=lambda: now, process_alive=lambda pid: alive.get(pid, False),
        )
        first = first_runtime.create(self.project, candidate_id="candidate-one")
        later = lambda: now + timedelta(minutes=1)
        live_runtime = WorktreeRuntime(
            self.root / "state", clock=later, process_alive=lambda pid: alive.get(pid, False),
        )
        with self.assertRaises(RepositoryBusy):
            live_runtime.create(self.project, candidate_id="candidate-two")

        alive[os.getpid()] = False
        recovered_runtime = WorktreeRuntime(
            self.root / "state", clock=later, process_alive=lambda pid: alive.get(pid, False),
        )
        recovered = recovered_runtime.create(self.project, candidate_id="candidate-two")
        try:
            self.assertEqual(recovered.candidate_id, "candidate-two")
        finally:
            recovered_runtime.close(recovered)
            # The stale owner's close must not remove the replacement owner's lock.
            first_runtime.close(first)

    def test_candidate_commit_preserves_additions_and_deletions_without_copying_back(self):
        """Using a tracked-only diff or copying files to the source must fail this test."""
        session = self.runtime.create(self.project, candidate_id="candidate-tree")
        working = Path(session.working_root)
        (working / "README.md").unlink()
        (working / "ADDED.txt").write_text("candidate\n", encoding="utf-8")

        commit = self.runtime.commit(session, "candidate tree")

        self.assertEqual(git(working, "show", "--format=", "--name-status", commit).splitlines(), [
            "A\tADDED.txt", "D\tREADME.md",
        ])
        self.assertTrue((self.project / "README.md").exists())
        self.assertFalse((self.project / "ADDED.txt").exists())
        with self.assertRaisesRegex(PermissionError, "authoritative"):
            self.runtime.apply(session, approved_fingerprint=session.baseline_fingerprint)
        self.runtime.close(session)

    def test_symlink_or_reparse_content_is_rejected(self):
        """Following a repository link outside the approved root must fail this test."""
        outside = self.root / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        link = self.project / "linked.txt"
        try:
            link.symlink_to(outside)
        except OSError as error:
            self.skipTest(f"symlink creation is unavailable: {error}")

        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", ResourceWarning)
            with self.assertRaisesRegex(ValueError, "symlink|reparse"):
                self.runtime.create(self.project, candidate_id="candidate-link")
            gc.collect()
        self.assertEqual(
            [item for item in observed if issubclass(item.category, ResourceWarning)], []
        )


if __name__ == "__main__":
    unittest.main()
