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
        with self.assertRaisesRegex(ValidationError, "push must be the final action"):
            BrokerActionRequest(
                schema_version=1, project_root="C:/repo", baseline_fingerprint="clean",
                actions=[{"kind": "push"}, {"kind": "apply_patch", "patch": "diff"}],
            )
        with self.assertRaisesRegex(ValidationError, "aggregate patch"):
            BrokerActionRequest(
                schema_version=1, project_root="C:/repo", baseline_fingerprint="clean",
                actions=[{"kind": "apply_patch", "patch": "x" * 130_000},
                         {"kind": "apply_patch", "patch": "y" * 130_000}],
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

            first_dirty = dirty.dirty_fingerprint
            (project / "README.md").write_text("another\n", encoding="utf-8")
            self.assertNotEqual(first_dirty, service.inspect(project).dirty_fingerprint)

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


class GitBrokerAuditTests(unittest.TestCase):
    def test_audit_persists_without_prompt_or_environment_and_recovers_running_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = GitBrokerService(root / "data")
            service.record_audit({
                "id": "task-1", "status": "running", "project_root": "C:/repo", "model": "qwen",
                "prompt": "secret task", "environment": {"TOKEN": "secret"},
            })

            reloaded = GitBrokerService(root / "data")
            recovered = reloaded.recover_interrupted_tasks()
            text = (root / "data" / "git-broker-audit.json").read_text(encoding="utf-8")

            self.assertEqual(recovered[0]["status"], "interrupted")
            self.assertNotIn("secret task", text)
            self.assertNotIn("TOKEN", text)


class GitBrokerExecutionTests(unittest.TestCase):
    def _repository(self, root: Path) -> tuple[Path, Path]:
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
        return project, remote

    def test_execute_applies_commits_rebases_and_pushes_with_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, remote = self._repository(root)
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[
                    {"kind": "apply_patch", "patch": "diff --git a/README.md b/README.md\nindex e79c5e8..b03d9db 100644\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-initial\n+updated\n"},
                    {"kind": "commit", "message": "Update readme"},
                    {"kind": "push"},
                ],
            )

            result = service.execute(request, model="qwen2.5-coder:7b", grant_id="grant-1")

            self.assertEqual(result.status, "pushed")
            self.assertEqual(git(project, "show", "-s", "--format=%an <%ae>", "HEAD"), "Test User <test@example.com>")
            message = git(project, "show", "-s", "--format=%B", "HEAD")
            self.assertIn("JSON-CODR-Model: qwen2.5-coder:7b", message)
            self.assertIn("JSON-CODR-Profile: broker", message)
            self.assertIn("JSON-CODR-Grant: grant-1", message)
            self.assertEqual(git(remote, "show", "main:README.md"), "updated")

    def test_execute_stops_when_baseline_does_not_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self._repository(root)
            service = GitBrokerService(root / "data")
            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint="0" * 64,
                actions=[{"kind": "status"}],
            )

            with self.assertRaisesRegex(RuntimeError, "changed since authorization"):
                service.execute(request, model="qwen", grant_id="grant-1")

    def test_local_status_does_not_fetch_or_change_remote_tracking_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, remote = self._repository(root)
            initial_remote_head = git(project, "rev-parse", "refs/remotes/origin/main")
            publisher = root / "publisher"
            git(root, "clone", "-b", "main", str(remote), str(publisher))
            git(publisher, "config", "user.name", "Remote User")
            git(publisher, "config", "user.email", "remote@example.com")
            (publisher / "REMOTE.md").write_text("remote\n", encoding="utf-8")
            git(publisher, "add", "REMOTE.md")
            git(publisher, "commit", "-m", "remote change")
            git(publisher, "push", "origin", "HEAD:main")
            remote_head = git(remote, "rev-parse", "main")
            self.assertNotEqual(initial_remote_head, remote_head)
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            request = BrokerActionRequest(
                schema_version=1,
                project_root=str(project),
                baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[{"kind": "status"}],
            )

            service.execute(request, model="qwen", grant_id="grant-1")

            self.assertEqual(git(project, "rev-parse", "refs/remotes/origin/main"), initial_remote_head)

    def test_execute_can_create_read_review_and_run_allowlisted_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self._repository(root)
            service = GitBrokerService(root / "data", verification_checks={
                "python-smoke": ["python", "-c", "print('CHECK_OK')"],
            })
            baseline = service.inspect(project)
            patch = (
                "diff --git a/hello.py b/hello.py\nnew file mode 100644\nindex 0000000..b376c99\n"
                "--- /dev/null\n+++ b/hello.py\n@@ -0,0 +1 @@\n+print('hello')\n"
            )
            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[
                    {"kind": "apply_patch", "patch": patch},
                    {"kind": "read", "paths": ["hello.py"]},
                    {"kind": "verify", "checks": ["python-smoke"]},
                    {"kind": "status"},
                ],
            )

            result = service.execute(request, model="qwen", grant_id="grant-1")

            self.assertEqual(result.outputs["files"]["hello.py"], "print('hello')\n")
            self.assertEqual(result.outputs["checks"]["python-smoke"], "CHECK_OK")
            self.assertIn("hello.py", result.outputs["diff"])

    def test_execute_rejects_unconfigured_verification_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self._repository(root)
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[{"kind": "verify", "checks": ["arbitrary-shell"]}],
            )
            with self.assertRaisesRegex(ValueError, "not configured"):
                service.execute(request, model="qwen", grant_id="grant-1")

    def test_execute_rechecks_authorization_after_waiting_for_project_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self._repository(root)
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[{"kind": "status"}],
            )
            with self.assertRaisesRegex(PermissionError, "revoked"):
                service.execute(request, model="qwen", grant_id="grant-1", authorized=lambda: False)


if __name__ == "__main__":
    unittest.main()
