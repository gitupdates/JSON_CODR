import subprocess
import tempfile
import unittest
from pathlib import Path


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=self.root, check=True, capture_output=True)

    def tearDown(self):
        subprocess.run(["git", "worktree", "prune"], cwd=self.root, capture_output=True)
        self.temporary.cleanup()

    def test_verified_candidate_requires_digest_bound_approval_and_can_rollback(self):
        from web_app.core.promotion import PromotionService
        from web_app.git_broker import GitBrokerService

        service = PromotionService(
            self.root,
            Path(self.temporary.name) / "promotion",
            GitBrokerService(Path(self.temporary.name) / "broker"),
        )
        candidate = service.stage("HEAD")
        (Path(candidate.worktree_root) / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        manifest = service.verify(candidate)

        with self.assertRaisesRegex(PermissionError, "approval"):
            service.promote(candidate, "sha256:" + "0" * 64)

        result = service.promote(candidate, manifest.digest)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")
        service.rollback(result.snapshot_id)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_syntax_failure_cannot_produce_verification_manifest(self):
        from web_app.core.promotion import PromotionService
        from web_app.git_broker import GitBrokerService

        service = PromotionService(
            self.root,
            Path(self.temporary.name) / "promotion-bad",
            GitBrokerService(Path(self.temporary.name) / "broker-bad"),
        )
        candidate = service.stage("HEAD")
        (Path(candidate.worktree_root) / "app.py").write_text("def broken(:\n", encoding="utf-8")

        with self.assertRaises(SyntaxError):
            service.verify(candidate)


if __name__ == "__main__":
    unittest.main()
