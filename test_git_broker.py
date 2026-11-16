import subprocess
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from web_app.git_broker import GitBrokerService
from web_app.models import BrokerActionRequest


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


class GitBrokerContractTests(unittest.TestCase):
    def test_request_is_strict_versioned_and_bounded(self):
        request = BrokerActionRequest(
            schema_version=1,
            project_root="C:/repo",
            actions=[{"kind": "status"}],
            baseline_fingerprint="clean",
        )
        self.assertEqual(request.schema_version, 1)
        self.assertEqual(request.actions[0].kind, "status")

        with self.assertRaises(ValidationError):
            BrokerActionRequest(
                schema_version=2,
                project_root="C:/repo",
                actions=[{"kind": "status"}],
                baseline_fingerprint="clean",
            )
        with self.assertRaises(ValidationError):
            BrokerActionRequest(
                schema_version=1,
                project_root="C:/repo",
                actions=[{"kind": "status", "command": "whoami"}],
                baseline_fingerprint="clean",
            )

    def test_request_rejects_traversal_and_oversized_patch(self):
        with self.assertRaises(ValidationError):
            BrokerActionRequest(
                schema_version=1,
                project_root="C:/repo",
                actions=[{"kind": "read", "paths": ["../secret"]}],
                baseline_fingerprint="clean",
            )
        with self.assertRaises(ValidationError):
            BrokerActionRequest(
                schema_version=1,
                project_root="C:/repo",
                actions=[{"kind": "apply_patch", "patch": "x" * 200_001}],
                baseline_fingerprint="clean",
            )


class GitBrokerInspectionTests(unittest.TestCase):
    def test_inspect_reports_branch_upstream_and_dirty_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            project = root / "project"
            git(root, "init", "--bare", str(remote))
            git(root, "init", "-b", "main", str(project))
            git(project, "config", "user.name", "Test User")
            git(project, "config", "user.email", "test@example.com")
            (project / "README.md").write_text("initial\n", encoding="utf-8")
            git(project, "add", "README.md")
            git(project, "commit", "-m", "initial")
            git(project, "remote", "add", "origin", str(remote))
            git(project, "push", "-u", "origin", "main")
            service = GitBrokerService(root / "data")

            clean = service.inspect(project)
            (project / "README.md").write_text("changed\n", encoding="utf-8")
            dirty = service.inspect(project)

            self.assertEqual(clean.branch, "main")
            self.assertEqual(clean.upstream, "origin/main")
            self.assertEqual(clean.remote_head, clean.head)
            self.assertTrue(clean.clean)
            self.assertFalse(dirty.clean)
            self.assertNotEqual(clean.dirty_fingerprint, dirty.dirty_fingerprint)

    def test_inspect_rejects_non_repository_and_symlink_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = GitBrokerService(root / "data")
            with self.assertRaisesRegex(ValueError, "Git repository"):
                service.inspect(root)
            project = root / "project"
            project.mkdir()
            git(project, "init")
            link = root / "linked"
            try:
                link.symlink_to(project, target_is_directory=True)
            except OSError:
                self.skipTest("Directory symlinks are unavailable")
            with self.assertRaisesRegex(ValueError, "reparse"):
                service.inspect(link)


if __name__ == "__main__":
    unittest.main()
