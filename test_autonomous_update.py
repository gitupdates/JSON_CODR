import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from web_app.core.autonomous_update import (
    AmbiguousEffect,
    AutonomousUpdateController,
    CandidateState,
    InvalidCandidateTransition,
    UpdateProfile,
)
from web_app.core.git_adapter import VerificationReceipt
from web_app.core.identity import AuthenticatedPrincipal
from web_app.core.store import TaskStore
from web_app.core.worktree_runtime import RepositoryBusy, WorktreeRuntime
from web_app.core.update_launcher import HealthReceipt


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout.strip()


class RecordingVerifier:
    def __init__(self):
        self.calls = 0

    def verify(self, *, candidate_id, base_sha, tree_sha, checks, project_root):
        self.calls += 1
        return VerificationReceipt(
            candidate_id=candidate_id,
            base_sha=base_sha,
            tree_sha=tree_sha,
            profile_digest="sha256:" + "a" * 64,
            checks=checks,
            verified_at=datetime.now(UTC),
            verifier_credential_id="verifier-1",
        )

    def validate(self, receipt):
        return receipt.verifier_credential_id == "verifier-1"


class RecordingPublisher:
    def __init__(self):
        self.calls = 0

    def publish_verified(self, project_root, branch, commit_sha, expected_remote_sha):
        self.calls += 1
        return {
            "publication_id": f"publication-{commit_sha[:8]}",
            "branch": branch,
            "commit_sha": commit_sha,
            "previous_remote_sha": expected_remote_sha,
            "remote_sha": commit_sha,
            "status": "published",
        }


class RecordingLauncher:
    def __init__(self):
        self.launches = 0
        self.activations = 0
        self.rollbacks = 0

    def launch_candidate(self, candidate, profile):
        self.launches += 1
        return {
            "health_id": f"health-{candidate.candidate_id}",
            "candidate_id": candidate.candidate_id,
            "revision": candidate.commit_sha,
            "version": "V1.3.9",
            "healthy": True,
            "checks": ["startup", "api", "ui"],
        }

    def activate(self, receipt):
        self.activations += 1
        return {
            "activation_id": "activation-1", "revision": receipt["revision"],
            "previous_revision": "previous", "status": "activated",
        }

    def rollback(self, activation_id):
        self.rollbacks += 1
        return {
            "rollback_id": "rollback-1", "activation_id": activation_id,
            "restored_revision": "previous", "status": "rolled_back",
        }


class AutonomousUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        git(self.project, "init", "-b", "main")
        git(self.project, "config", "user.name", "JSON CODR Tests")
        git(self.project, "config", "user.email", "tests@example.invalid")
        (self.project / "README.md").write_text("initial\n", encoding="utf-8")
        git(self.project, "add", "README.md")
        git(self.project, "commit", "-m", "initial")
        self.base_sha = git(self.project, "rev-parse", "HEAD")
        self.store = TaskStore(self.root / "state" / "tasks.sqlite")
        self.worktrees = WorktreeRuntime(self.root / "state" / "candidates")
        self.verifier = RecordingVerifier()
        self.publisher = RecordingPublisher()
        self.launcher = RecordingLauncher()
        self.profile = UpdateProfile(
            profile_id="self-update",
            repository_root=str(self.project),
            branch="main",
            expected_remote_sha=self.base_sha,
            mandatory_checks=("unit",),
            allowed_repository_roots=(str(self.root),),
        )
        self.principal = AuthenticatedPrincipal(
            user_id="administrator", username="Administrator", roles=("administrator",),
            credential_id="service-1", credential_kind="service",
            scopes=("system.update", "system.activate", "system.rollback"),
        )
        self.controller = self._controller(self.store, self.worktrees)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def _controller(self, store, worktrees):
        return AutonomousUpdateController(
            store=store,
            profiles={self.profile.profile_id: self.profile},
            worktrees=worktrees,
            verifier=self.verifier,
            publisher=self.publisher,
            launcher=self.launcher,
        )

    def _verified(self):
        candidate = self.controller.propose("self-update", "Improve JSON CODR", self.principal)
        candidate = self.controller.stage(candidate.candidate_id)
        working = Path(candidate.worktree.working_root)
        (working / "README.md").write_text("candidate\n", encoding="utf-8")
        candidate = self.controller.mark_modified(candidate.candidate_id)
        return self.controller.verify(candidate.candidate_id)

    def test_full_lifecycle_projects_from_durable_task_events(self):
        """Skipping any lifecycle gate or using mutable candidate JSON must fail this test."""
        candidate = self._verified()
        self.assertEqual(candidate.state, CandidateState.verified)
        candidate = self.controller.commit(candidate.candidate_id)
        candidate = self.controller.publish(candidate.candidate_id)
        candidate = self.controller.health_check(candidate.candidate_id)
        candidate = self.controller.activate(candidate.candidate_id)
        candidate = self.controller.rollback(candidate.candidate_id)

        self.assertEqual(candidate.state, CandidateState.rolled_back)
        self.assertEqual(self.verifier.calls, 1)
        self.assertEqual(self.publisher.calls, 1)
        self.assertEqual(self.launcher.launches, 1)
        self.assertEqual(self.launcher.activations, 1)
        self.assertEqual(self.launcher.rollbacks, 1)
        events = self.store.events(candidate.task_id)
        self.assertTrue(all(event.__class__.__name__ == "TaskEvent" for event in events))
        self.assertIn("candidate.verification_completed", [event.event_type for event in events])

    def test_forbidden_skips_are_rejected_and_duplicate_commands_are_idempotent(self):
        """A missing state guard or effect idempotency receipt must fail this test."""
        candidate = self.controller.propose("self-update", "Improve JSON CODR", self.principal)
        with self.assertRaises(InvalidCandidateTransition):
            self.controller.commit(candidate.candidate_id)

        first = self.controller.stage(candidate.candidate_id)
        repeated = self.controller.stage(candidate.candidate_id)
        self.assertEqual(first, repeated)
        (Path(first.worktree.working_root) / "README.md").write_text("candidate\n", encoding="utf-8")
        self.controller.mark_modified(candidate.candidate_id)
        verified = self.controller.verify(candidate.candidate_id)
        self.assertEqual(self.controller.verify(candidate.candidate_id), verified)
        self.assertEqual(self.verifier.calls, 1)
        self.assertEqual(len(self.store.effects(candidate.task_id)), 2)

    def test_restart_recovers_projection_and_does_not_repeat_effects(self):
        """Keeping lifecycle state only in controller memory must fail this test."""
        candidate = self._verified()
        candidate_id = candidate.candidate_id
        self.store.close()
        reopened = TaskStore(self.root / "state" / "tasks.sqlite")
        try:
            restarted = self._controller(reopened, WorktreeRuntime(self.root / "state" / "candidates"))
            projected = restarted.get(candidate_id)
            self.assertEqual(projected.state, CandidateState.verified)
            self.assertEqual(restarted.verify(candidate_id), projected)
            self.assertEqual(self.verifier.calls, 1)
        finally:
            self.store = reopened

    def test_two_candidates_cannot_write_the_same_repository(self):
        """A process-local writer guard would allow this second controller to stage."""
        first = self.controller.propose("self-update", "first", self.principal)
        self.controller.stage(first.candidate_id)
        second_store = TaskStore(self.root / "state" / "second.sqlite")
        try:
            second = self._controller(
                second_store, WorktreeRuntime(self.root / "state" / "candidates")
            ).propose("self-update", "second", self.principal)
            other = self._controller(
                second_store, WorktreeRuntime(self.root / "state" / "candidates")
            )
            with self.assertRaises(RepositoryBusy):
                other.stage(second.candidate_id)
        finally:
            second_store.close()

    def test_ambiguous_effect_must_be_reconciled_before_retry(self):
        """Blindly retrying an ambiguous external operation must fail this test."""
        class AmbiguousPublisher(RecordingPublisher):
            def publish_verified(self, *args, **kwargs):
                self.calls += 1
                raise AmbiguousEffect("network result unknown")

            def reconcile_publication(self, branch, commit_sha):
                return {
                    "publication_id": "reconciled", "branch": branch,
                    "commit_sha": commit_sha, "remote_sha": commit_sha,
                    "status": "published",
                }

        publisher = AmbiguousPublisher()
        self.controller = AutonomousUpdateController(
            store=self.store, profiles={self.profile.profile_id: self.profile},
            worktrees=self.worktrees, verifier=self.verifier,
            publisher=publisher, launcher=self.launcher,
        )
        candidate = self.controller.commit(self._verified().candidate_id)
        with self.assertRaises(AmbiguousEffect):
            self.controller.publish(candidate.candidate_id)
        with self.assertRaises(InvalidCandidateTransition):
            self.controller.publish(candidate.candidate_id)

        reconciled = self.controller.reconcile(candidate.candidate_id, "publish")
        self.assertEqual(reconciled.state, CandidateState.published)
        self.assertEqual(publisher.calls, 1)

    def test_reconciled_not_applied_publication_can_retry_once_safely(self):
        """A failed outbox row must not permanently strand a proven-not-applied publication."""
        class RetryPublisher(RecordingPublisher):
            def __init__(self):
                super().__init__()
                self.first = True

            def publish_verified(self, *args, **kwargs):
                self.calls += 1
                if self.first:
                    self.first = False
                    raise AmbiguousEffect("network result unknown")
                return {
                    "publication_id": "retried", "branch": args[1],
                    "commit_sha": args[2], "remote_sha": args[2], "status": "published",
                }

            def reconcile_publication(self, branch, commit_sha):
                return {
                    "branch": branch, "commit_sha": commit_sha,
                    "remote_sha": None, "status": "not_published",
                }

        publisher = RetryPublisher()
        self.controller = AutonomousUpdateController(
            store=self.store, profiles={self.profile.profile_id: self.profile},
            worktrees=self.worktrees, verifier=self.verifier,
            publisher=publisher, launcher=self.launcher,
        )
        candidate = self.controller.commit(self._verified().candidate_id)
        with self.assertRaises(AmbiguousEffect):
            self.controller.publish(candidate.candidate_id)

        reconciled = self.controller.reconcile(candidate.candidate_id, "publish")
        self.assertEqual(reconciled.state, CandidateState.committed)
        published = self.controller.publish(candidate.candidate_id)
        self.assertEqual(published.state, CandidateState.published)
        self.assertEqual(publisher.calls, 2)

    def test_candidate_health_failure_persists_typed_failure_evidence(self):
        """Dropping launcher evidence from the durable failure event must fail this test."""
        from web_app.core.update_launcher import CandidateHealthError

        class FailingLauncher(RecordingLauncher):
            def launch_candidate(self, candidate, profile):
                raise CandidateHealthError(HealthReceipt(
                    health_id="failed-health", candidate_id=candidate.candidate_id,
                    revision=candidate.commit_sha, root=candidate.worktree.working_root,
                    version="V1.3.9", host="127.0.0.1", port=43210,
                    data_root=str(self_root / "failed-data"), pid=None, healthy=False,
                    checks=("startup", "api"), error="candidate API failed",
                    migration_compatibility="backward_compatible",
                ))

        self_root = self.root
        launcher = FailingLauncher()
        self.controller = AutonomousUpdateController(
            store=self.store, profiles={self.profile.profile_id: self.profile},
            worktrees=self.worktrees, verifier=self.verifier,
            publisher=self.publisher, launcher=launcher,
        )
        candidate = self.controller.publish(self.controller.commit(self._verified().candidate_id).candidate_id)
        with self.assertRaises(CandidateHealthError):
            self.controller.health_check(candidate.candidate_id)
        failure = next(
            event for event in self.store.events(candidate.task_id)
            if event.event_type == "candidate.health_failed"
        )
        self.assertEqual(failure.payload["receipt"]["health_id"], "failed-health")


if __name__ == "__main__":
    unittest.main()
