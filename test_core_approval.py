import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from web_app.core.adapters import CapabilityCall
from web_app.core.adapters import AdapterEvent
from web_app.core.approval import ApprovalStore
from web_app.core.contracts import TaskCommand, TaskStatus
from web_app.core.policy import PolicyEffect, PolicyService
from web_app.core.project_registry import ProjectRegistry
from web_app.core.service import CoreService
from web_app.core.store import TaskStore


class ApprovalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "approvals.sqlite"
        self.store = ApprovalStore(self.database)
        self.call = CapabilityCall(
            capability_id="project.patch",
            operation="replace",
            project_root=self.temporary.name,
            target_path="module.py",
            arguments={"content": "answer = 42\n"},
        )
        self.fingerprint = "sha256:" + "1" * 64

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def propose(self, **updates):
        values = {
            "principal": "user",
            "project_id": "project-1",
            "task_id": "task-1",
            "step_id": "step-1",
            "step_revision": 1,
            "call": self.call,
            "project_fingerprint": self.fingerprint,
        }
        values.update(updates)
        return self.store.propose(**values)

    def test_lease_is_bound_to_exact_call_principal_revision_and_fingerprint(self):
        proposal = self.propose()

        lease = self.store.consume(
            proposal.proposal_id,
            principal="user",
            call=self.call,
            project_fingerprint=self.fingerprint,
            step_revision=1,
        )

        self.assertEqual(lease.proposal_id, proposal.proposal_id)
        self.assertEqual(lease.call_digest, proposal.call_digest)
        self.assertEqual(lease.status, "consumed")
        changed_call = self.call.model_copy(update={"target_path": "other.py"})
        for changes, message in (
            ({"principal": "other"}, "principal"),
            ({"call": changed_call}, "call"),
            ({"project_fingerprint": "sha256:" + "2" * 64}, "fingerprint"),
            ({"step_revision": 2}, "revision"),
        ):
            fresh = self.propose()
            arguments = {
                "principal": "user", "call": self.call,
                "project_fingerprint": self.fingerprint, "step_revision": 1,
            }
            arguments.update(changes)
            with self.assertRaisesRegex(PermissionError, message):
                self.store.consume(fresh.proposal_id, **arguments)

    def test_lease_is_one_use_across_store_connections(self):
        proposal = self.propose()
        other = ApprovalStore(self.database)
        try:
            self.store.consume(
                proposal.proposal_id, principal="user", call=self.call,
                project_fingerprint=self.fingerprint, step_revision=1,
            )
            with self.assertRaisesRegex(PermissionError, "already consumed"):
                other.consume(
                    proposal.proposal_id, principal="user", call=self.call,
                    project_fingerprint=self.fingerprint, step_revision=1,
                )
        finally:
            other.close()

    def test_expired_rejected_and_revoked_proposals_cannot_be_consumed(self):
        now = datetime.now(UTC)
        expired = self.propose(expires_at=now - timedelta(seconds=1))
        rejected = self.propose()
        revoked = self.propose(task_id="task-2")
        self.store.reject(rejected.proposal_id, principal="user")
        self.store.revoke_task("task-2")

        for proposal, message in (
            (expired, "expired"), (rejected, "rejected"), (revoked, "revoked"),
        ):
            with self.assertRaisesRegex(PermissionError, message):
                self.store.consume(
                    proposal.proposal_id, principal="user", call=self.call,
                    project_fingerprint=self.fingerprint, step_revision=1, now=now,
                )

    def test_reopening_preserves_pending_proposal_without_credentials(self):
        call = self.call.model_copy(update={"credential_refs": ("credential:deploy",)})
        proposal = self.propose(call=call)
        self.store.close()
        self.store = ApprovalStore(self.database)

        restored = self.store.get(proposal.proposal_id)
        database_text = self.database.read_bytes()

        self.assertEqual(restored.call_digest, proposal.call_digest)
        self.assertNotIn(b"deploy", database_text)

    def test_envelope_consumes_each_exact_call_once_and_emits_final_receipt(self):
        envelope = self.store.propose_envelope(
            principal="user", project_id="project-1", task_id="task-1",
            task_revision=3, calls=(self.call, self.call),
            project_fingerprint=self.fingerprint,
        )
        approved = self.store.approve_envelope(
            envelope.envelope_id, principal="user", project_id="project-1",
            project_fingerprint=self.fingerprint, task_revision=3,
        )
        self.assertEqual(approved.status, "approved")

        first = self.store.reserve_envelope_call(
            envelope.envelope_id, principal="user", project_id="project-1",
            call=self.call, project_fingerprint=self.fingerprint, task_revision=3,
        )
        next_fingerprint = "sha256:" + "2" * 64
        self.assertIsNone(self.store.record_envelope_result(
            first, project_fingerprint=next_fingerprint, outcome="completed",
        ))
        second = self.store.reserve_envelope_call(
            envelope.envelope_id, principal="user", project_id="project-1",
            call=self.call, project_fingerprint=next_fingerprint, task_revision=3,
        )
        receipt = self.store.record_envelope_result(
            second, project_fingerprint=next_fingerprint, outcome="completed",
        )

        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.call_digests, (envelope.calls[0].call_digest,) * 2)
        self.assertEqual(receipt.outcomes, ("completed", "completed"))
        self.assertRegex(receipt.receipt_digest, r"^sha256:[0-9a-f]{64}$")
        with self.assertRaisesRegex(PermissionError, "replay"):
            self.store.reserve_envelope_call(
                envelope.envelope_id, principal="user", project_id="project-1",
                call=self.call, project_fingerprint=next_fingerprint, task_revision=3,
            )

    def test_envelope_rejects_scope_changes_and_out_of_envelope_calls(self):
        envelope = self.store.propose_envelope(
            principal="user", project_id="project-1", task_id="task-1",
            task_revision=1, calls=(self.call,), project_fingerprint=self.fingerprint,
        )
        changed = self.call.model_copy(update={"target_path": "other.py"})
        checks = (
            ({"principal": "other"}, "principal"),
            ({"project_id": "project-2"}, "project"),
            ({"project_fingerprint": "sha256:" + "2" * 64}, "fingerprint"),
            ({"task_revision": 2}, "revision"),
        )
        for updates, message in checks:
            arguments = {
                "principal": "user", "project_id": "project-1",
                "project_fingerprint": self.fingerprint, "task_revision": 1,
            }
            arguments.update(updates)
            with self.assertRaisesRegex(PermissionError, message):
                self.store.approve_envelope(envelope.envelope_id, **arguments)
        self.store.approve_envelope(
            envelope.envelope_id, principal="user", project_id="project-1",
            project_fingerprint=self.fingerprint, task_revision=1,
        )
        for updates, message in (
            ({"principal": "other"}, "principal"),
            ({"project_id": "project-2"}, "project"),
            ({"project_fingerprint": "sha256:" + "2" * 64}, "fingerprint"),
            ({"task_revision": 2}, "revision"),
        ):
            arguments = {
                "principal": "user", "project_id": "project-1", "call": self.call,
                "project_fingerprint": self.fingerprint, "task_revision": 1,
            }
            arguments.update(updates)
            with self.assertRaisesRegex(PermissionError, message):
                self.store.reserve_envelope_call(envelope.envelope_id, **arguments)
        with self.assertRaisesRegex(PermissionError, "outside"):
            self.store.reserve_envelope_call(
                envelope.envelope_id, principal="user", project_id="project-1",
                call=changed, project_fingerprint=self.fingerprint, task_revision=1,
            )

    def test_envelope_refuses_destructive_or_scope_expanding_calls(self):
        destructive = self.call.model_copy(update={
            "capability_id": "checkpoint.restore", "operation": "destructive",
        })
        expanding = self.call.model_copy(update={
            "capability_id": "component.install", "operation": "install",
        })
        networked = self.call.model_copy(update={
            "capability_id": "api.test", "operation": "test",
        })
        for call in (destructive, expanding, networked):
            with self.assertRaisesRegex(PermissionError, "separate approval"):
                self.store.propose_envelope(
                    principal="user", project_id="project-1", task_id="task-1",
                    task_revision=1, calls=(call,), project_fingerprint=self.fingerprint,
                )

    def test_concurrent_envelope_reservation_has_one_winner(self):
        envelope = self.store.propose_envelope(
            principal="user", project_id="project-1", task_id="task-1",
            task_revision=1, calls=(self.call,), project_fingerprint=self.fingerprint,
        )
        self.store.approve_envelope(
            envelope.envelope_id, principal="user", project_id="project-1",
            project_fingerprint=self.fingerprint, task_revision=1,
        )
        barrier = threading.Barrier(2)
        outcomes = []

        def reserve():
            other = ApprovalStore(self.database)
            try:
                barrier.wait()
                other.reserve_envelope_call(
                    envelope.envelope_id, principal="user", project_id="project-1",
                    call=self.call, project_fingerprint=self.fingerprint, task_revision=1,
                )
                outcomes.append("reserved")
            except PermissionError:
                outcomes.append("rejected")
            finally:
                other.close()

        threads = [threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["reserved", "rejected"])

    def test_expired_and_revoked_envelopes_fail_closed(self):
        now = datetime.now(UTC)
        expired = self.store.propose_envelope(
            principal="user", project_id="project-1", task_id="expired-task",
            task_revision=1, calls=(self.call,), project_fingerprint=self.fingerprint,
            expires_at=now - timedelta(seconds=1),
        )
        with self.assertRaisesRegex(PermissionError, "expired"):
            self.store.approve_envelope(
                expired.envelope_id, principal="user", project_id="project-1",
                project_fingerprint=self.fingerprint, task_revision=1, now=now,
            )
        revocable = self.store.propose_envelope(
            principal="user", project_id="project-1", task_id="revoked-task",
            task_revision=1, calls=(self.call,), project_fingerprint=self.fingerprint,
        )
        self.store.approve_envelope(
            revocable.envelope_id, principal="user", project_id="project-1",
            project_fingerprint=self.fingerprint, task_revision=1,
        )
        self.store.revoke_task("revoked-task")
        with self.assertRaisesRegex(PermissionError, "revoked"):
            self.store.reserve_envelope_call(
                revocable.envelope_id, principal="user", project_id="project-1",
                call=self.call, project_fingerprint=self.fingerprint, task_revision=1,
            )


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    async def execute(self, call, context):
        self.calls.append(call)
        yield AdapterEvent(event_type="git.completed", payload={"status": "committed"})


class ExactApprovalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tasks = TaskStore(self.root / "tasks.sqlite")
        self.policy = PolicyService(self.root / "policy.sqlite")
        self.projects = ProjectRegistry(self.root / "projects.sqlite")
        self.projects.register(self.root, project_id="project-1")
        self.approvals = ApprovalStore(self.root / "approvals.sqlite")
        self.adapter = RecordingAdapter()
        self.fingerprint = "sha256:" + "1" * 64
        self.service = CoreService(
            self.tasks,
            self.policy,
            {"git.execute": self.adapter},
            approval_store=self.approvals,
            project_fingerprint=lambda _root: self.fingerprint,
            project_roots=self.projects,
        )

    async def asyncTearDown(self):
        await self.service.shutdown()
        self.approvals.close()
        self.policy.close()
        self.tasks.close()
        self.projects.close()
        self.temporary.cleanup()

    def command(self, suffix="1"):
        call = CapabilityCall(
            capability_id="git.execute", operation="git", project_root=str(self.root),
            arguments={"request_id": suffix},
        )
        return TaskCommand(
            command_id=f"command-{suffix}", task_id=f"task-{suffix}", thread_id="thread-1",
            project_id="project-1", command_type="git.execute", payload=call.model_dump(mode="json"),
        )

    async def test_sensitive_call_executes_once_without_persistent_policy_grant(self):
        command = self.command()
        waiting = await self.service.submit(command)
        proposal_id = waiting.events[-1].payload["proposal_id"]

        completed = await self.service.approve(command.task_id, proposal_id=proposal_id)

        self.assertEqual(completed.status, TaskStatus.completed)
        self.assertEqual(len(self.adapter.calls), 1)
        call = CapabilityCall.model_validate(command.payload)
        self.assertEqual(self.policy.evaluate("user", "project-1", call).effect, PolicyEffect.require_approval)
        with self.assertRaisesRegex(PermissionError, "already consumed"):
            await self.service.approve(command.task_id, proposal_id=proposal_id)

    async def test_project_change_invalidates_exact_approval(self):
        command = self.command("stale")
        waiting = await self.service.submit(command)
        proposal_id = waiting.events[-1].payload["proposal_id"]
        self.fingerprint = "sha256:" + "2" * 64

        with self.assertRaisesRegex(PermissionError, "fingerprint"):
            await self.service.approve(command.task_id, proposal_id=proposal_id)

        self.assertEqual(self.adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
