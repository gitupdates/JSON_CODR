import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from web_app.git_broker import GitBrokerService, VerificationReceipt
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

    def test_publication_requires_verify_immediately_before_commit(self):
        """Removing final verification or moving it before an edit must reject publication."""
        values = {
            "schema_version": 1,
            "project_root": "C:/repo",
            "baseline_fingerprint": "clean",
        }
        for actions, message in (
            ([{"kind": "apply_patch", "patch": "diff"}, {"kind": "commit"}], "verify"),
            ([
                {"kind": "apply_patch", "patch": "diff"},
                {"kind": "verify", "checks": ["unit-tests"]},
                {"kind": "apply_patch", "patch": "diff"},
                {"kind": "commit"},
            ], "immediately"),
            ([
                {"kind": "apply_patch", "patch": "diff"},
                {"kind": "verify", "checks": ["unit-tests"]},
                {"kind": "commit"},
                {"kind": "apply_patch", "patch": "diff"},
                {"kind": "push"},
            ], "tree-changing"),
        ):
            with self.subTest(actions=actions):
                with self.assertRaisesRegex(ValidationError, message):
                    BrokerActionRequest(actions=actions, **values)
        with self.assertRaises(ValidationError):
            BrokerActionRequest(
                schema_version=1,
                project_root="C:/repo",
                actions=[{"kind": "apply_patch", "patch": "x" * 200_001}],
                baseline_fingerprint="clean",
            )


class GitBrokerInspectionTests(unittest.TestCase):
    def test_inspect_reports_branch_upstream_dirty_fingerprint_and_ahead_behind(self):
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
            self.assertEqual(clean.ahead, 0)
            self.assertEqual(clean.behind, 0)
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

    def _receipt(self, *, candidate_id: str, base_sha: str, tree_sha: str, profile_digest: str = "profiles-v1"):
        return VerificationReceipt(
            candidate_id=candidate_id,
            base_sha=base_sha,
            tree_sha=tree_sha,
            profile_digest=profile_digest,
            checks=("unit-tests",),
            verified_at=datetime.now(UTC),
            verifier_credential_id="verifier-credential",
        )

    def test_execute_applies_commits_rebases_and_pushes_with_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, remote = self._repository(root)
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            patch = "diff --git a/README.md b/README.md\nindex e79c5e8..b03d9db 100644\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-initial\n+updated\n"
            receipt = None

            def verify(action, *, candidate_id, base_sha, tree_sha):
                nonlocal receipt
                receipt = self._receipt(candidate_id=candidate_id, base_sha=base_sha, tree_sha=tree_sha)
                return receipt

            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[
                    {"kind": "apply_patch", "patch": patch},
                    {"kind": "verify", "checks": ["unit-tests"]},
                    {"kind": "commit", "message": "Update readme"},
                    {"kind": "push"},
                ],
            )

            result = service.execute(
                request, model="qwen2.5-coder:7b", grant_id="grant-1",
                verification_runner=verify,
                receipt_validator=lambda received: received == receipt,
            )

            self.assertEqual(result.status, "pushed")
            self.assertEqual(git(project, "show", "-s", "--format=%an <%ae>", "HEAD"), "Test User <test@example.com>")
            message = git(project, "show", "-s", "--format=%B", "HEAD")
            self.assertIn("JSON-CODR-Model: qwen2.5-coder:7b", message)
            self.assertIn("JSON-CODR-Profile: broker", message)
            self.assertIn("JSON-CODR-Grant: grant-1", message)
            self.assertEqual(git(remote, "show", "main:README.md"), "updated")

    def test_execute_rejects_failed_or_untrusted_final_verification(self):
        """A failed check or receipt that is not verifier-issued cannot authorize a commit."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self._repository(root)
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            patch = "diff --git a/README.md b/README.md\nindex e79c5e8..b03d9db 100644\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-initial\n+updated\n"
            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[
                    {"kind": "apply_patch", "patch": patch},
                    {"kind": "verify", "checks": ["unit-tests"]},
                    {"kind": "commit", "message": "Update readme"},
                ],
            )

            with self.assertRaisesRegex(RuntimeError, "Verification failed"):
                service.execute(
                    request, model="qwen", grant_id="candidate-1",
                    verification_runner=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Verification failed: unit-tests")),
                    receipt_validator=lambda receipt: True,
                )

            self.assertEqual(git(project, "rev-parse", "HEAD"), baseline.head)

    def test_execute_rejects_a_tree_changed_after_verification(self):
        """Changing the candidate after a receipt is issued must block the commit."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self._repository(root)
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            patch = "diff --git a/README.md b/README.md\nindex e79c5e8..b03d9db 100644\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-initial\n+updated\n"
            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[
                    {"kind": "apply_patch", "patch": patch},
                    {"kind": "verify", "checks": ["unit-tests"]},
                    {"kind": "commit", "message": "Update readme"},
                ],
            )

            def verify(action, *, candidate_id, base_sha, tree_sha):
                receipt = self._receipt(candidate_id=candidate_id, base_sha=base_sha, tree_sha=tree_sha)
                (project / "uncommitted.txt").write_text("changed after verify\n", encoding="utf-8")
                return receipt

            with self.assertRaisesRegex(RuntimeError, "final tree"):
                service.execute(
                    request, model="qwen", grant_id="candidate-1",
                    verification_runner=verify, receipt_validator=lambda receipt: True,
                )
            self.assertEqual(git(project, "rev-parse", "HEAD"), baseline.head)

    def test_execute_rejects_push_when_remote_advances_after_final_verification(self):
        """Rebasing after receipt validation would push a tree the verifier did not inspect."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, remote = self._repository(root)
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            patch = "diff --git a/README.md b/README.md\nindex e79c5e8..b03d9db 100644\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-initial\n+verified\n"
            receipt = None

            def verify(action, *, candidate_id, base_sha, tree_sha):
                nonlocal receipt
                receipt = self._receipt(candidate_id=candidate_id, base_sha=base_sha, tree_sha=tree_sha)
                return receipt

            publisher = root / "publisher"
            git(root, "clone", "-b", "main", str(remote), str(publisher))
            git(publisher, "config", "user.name", "Remote User")
            git(publisher, "config", "user.email", "remote@example.com")
            checks = 0

            def authorized():
                nonlocal checks
                checks += 1
                if checks == 4:
                    (publisher / "REMOTE.md").write_text("advanced\n", encoding="utf-8")
                    git(publisher, "add", "REMOTE.md")
                    git(publisher, "commit", "-m", "remote advance")
                    git(publisher, "push", "origin", "HEAD:main")
                return True

            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[
                    {"kind": "apply_patch", "patch": patch},
                    {"kind": "verify", "checks": ["unit-tests"]},
                    {"kind": "commit", "message": "Update readme"},
                    {"kind": "push"},
                ],
            )

            with self.assertRaisesRegex(RuntimeError, "upstream advanced"):
                service.execute(
                    request, model="qwen", grant_id="candidate-1", authorized=authorized,
                    verification_runner=verify, receipt_validator=lambda received: received == receipt,
                )

            self.assertEqual(git(remote, "show", "main:README.md"), "initial")
            self.assertEqual(git(remote, "show", "main:REMOTE.md"), "advanced")

    def test_execute_pushes_when_receipt_base_is_already_ahead_of_upstream(self):
        """An unchanged upstream may be an ancestor of a locally ahead receipt base."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, remote = self._repository(root)
            (project / "LOCAL.md").write_text("already local\n", encoding="utf-8")
            git(project, "add", "LOCAL.md")
            git(project, "commit", "-m", "local base")
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            patch = "diff --git a/README.md b/README.md\nindex e79c5e8..b03d9db 100644\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-initial\n+verified\n"
            receipt = None

            def verify(action, *, candidate_id, base_sha, tree_sha):
                nonlocal receipt
                receipt = self._receipt(candidate_id=candidate_id, base_sha=base_sha, tree_sha=tree_sha)
                return receipt

            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[
                    {"kind": "apply_patch", "patch": patch},
                    {"kind": "verify", "checks": ["unit-tests"]},
                    {"kind": "commit", "message": "Update readme"},
                    {"kind": "push"},
                ],
            )

            result = service.execute(
                request, model="qwen", grant_id="candidate-1",
                verification_runner=verify, receipt_validator=lambda received: received == receipt,
            )

            self.assertEqual(result.status, "pushed")
            self.assertEqual(git(remote, "show", "main:LOCAL.md"), "already local")
            self.assertEqual(git(remote, "show", "main:README.md"), "verified")

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
            service = GitBrokerService(root / "data")
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
                    {"kind": "verify", "checks": ["unit-tests"]},
                    {"kind": "status"},
                ],
            )

            result = service.execute(
                request, model="qwen", grant_id="grant-1",
                verification_runner=lambda action, **values: self._receipt(
                    candidate_id=values["candidate_id"], base_sha=values["base_sha"], tree_sha=values["tree_sha"],
                ),
                receipt_validator=lambda receipt: True,
            )

            self.assertEqual(result.outputs["files"]["hello.py"], "print('hello')\n")
            self.assertEqual(result.outputs["checks"]["unit-tests"], "verified")
            self.assertIn("hello.py", result.outputs["diff"])

    def test_execute_rejects_verification_without_a_trusted_profile_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self._repository(root)
            service = GitBrokerService(root / "data")
            baseline = service.inspect(project)
            request = BrokerActionRequest(
                schema_version=1, project_root=str(project), baseline_fingerprint=baseline.dirty_fingerprint,
                actions=[{"kind": "verify", "checks": ["arbitrary-shell"]}],
            )
            with self.assertRaisesRegex(RuntimeError, "trusted verification runner"):
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


class GitBrokerConflictRecoveryTests(unittest.TestCase):
    def _conflicting_worktree(self, root: Path):
        source = root / "source"
        candidate = root / "candidate"
        source.mkdir()
        git(source, "init", "-b", "main")
        git(source, "config", "user.name", "Test")
        git(source, "config", "user.email", "test@example.invalid")
        (source / "shared.txt").write_text("initial\n", encoding="utf-8")
        git(source, "add", "shared.txt")
        git(source, "commit", "-m", "initial")
        git(source, "worktree", "add", "-b", "candidate", str(candidate), "HEAD")
        (candidate / "shared.txt").write_text("candidate\n", encoding="utf-8")
        git(candidate, "add", "shared.txt")
        git(candidate, "commit", "-m", "candidate")
        (source / "shared.txt").write_text("upstream\n", encoding="utf-8")
        git(source, "add", "shared.txt")
        git(source, "commit", "-m", "upstream")
        return source, candidate, git(source, "rev-parse", "HEAD")

    def _git_path_exists(self, project: Path, name: str) -> bool:
        value = git(project, "rev-parse", "--git-path", name)
        path = Path(value)
        return (path if path.is_absolute() else project / path).exists()

    def test_rebase_conflict_is_aborted_inside_candidate_worktree(self):
        """Leaving REBASE_HEAD behind or rebasing the source repository must fail this test."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, candidate, upstream = self._conflicting_worktree(root)
            service = GitBrokerService(root / "data")

            with self.assertRaisesRegex(ValueError, "conflict|rebase"):
                service.rebase_candidate_worktree(candidate, upstream)

            self.assertFalse(self._git_path_exists(candidate, "rebase-merge"))
            self.assertFalse(self._git_path_exists(candidate, "rebase-apply"))
            self.assertEqual(git(source, "branch", "--show-current"), "main")

    def test_merge_conflict_is_aborted_inside_candidate_worktree(self):
        """Leaving MERGE_HEAD behind or accepting a normal checkout must fail this test."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, candidate, upstream = self._conflicting_worktree(root)
            service = GitBrokerService(root / "data")

            with self.assertRaisesRegex(ValueError, "conflict|merge"):
                service.merge_candidate_worktree(candidate, upstream)

            self.assertFalse(self._git_path_exists(candidate, "MERGE_HEAD"))
            with self.assertRaisesRegex(ValueError, "candidate worktree"):
                service.merge_candidate_worktree(source, "candidate")


if __name__ == "__main__":
    unittest.main()
