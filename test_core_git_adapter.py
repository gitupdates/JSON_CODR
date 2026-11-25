import asyncio
import unittest
from datetime import UTC, datetime

from web_app.core.adapters import CapabilityCall, ExecutionContext
from web_app.core.git_adapter import GitExecutionAdapter, GitVerificationService, VerificationReceipt


class _Profiles:
    def __init__(self):
        self.digest = "hmac-sha256:profiles-v1"

    def profile_digest(self):
        return self.digest


class _Runtime:
    async def run_profile(self, *, profile_id, values, project_root):
        self.profile_id = profile_id
        self.values = values
        self.project_root = project_root
        return type("Result", (), {"exit_code": 0, "timed_out": False, "stdout": "ok", "stderr": ""})()


class _VerifierIdentity:
    def __init__(self, credential_id="verifier-credential"):
        self.credential_id = credential_id

    def status(self):
        return type("Principal", (), {"credential_id": self.credential_id})()


class GitVerificationServiceTests(unittest.TestCase):
    def test_receipt_binds_final_tree_profiles_and_verifier_identity(self):
        """Changing the trusted profile digest or verifier credential invalidates an issued receipt."""
        profiles = _Profiles()
        runtime = _Runtime()
        identity = _VerifierIdentity()
        service = GitVerificationService(runtime, profiles, identity, signing_key=b"v" * 32)

        receipt = asyncio.run(service.verify(
            candidate_id="candidate-1", base_sha="base-sha", tree_sha="tree-sha",
            checks=("unit-tests",), project_root="C:/candidate",
        ))

        self.assertIsInstance(receipt, VerificationReceipt)
        self.assertEqual(receipt.candidate_id, "candidate-1")
        self.assertEqual(receipt.base_sha, "base-sha")
        self.assertEqual(receipt.tree_sha, "tree-sha")
        self.assertEqual(receipt.profile_digest, "hmac-sha256:profiles-v1")
        self.assertEqual(receipt.verifier_credential_id, "verifier-credential")
        self.assertTrue(service.validate(receipt))

        restarted = GitVerificationService(
            runtime, profiles, identity, signing_key=b"v" * 32
        )
        self.assertTrue(restarted.validate(receipt))
        self.assertFalse(restarted.validate(receipt.model_copy(update={"tree_sha": "other-tree"})))

        profiles.digest = "hmac-sha256:profiles-v2"
        self.assertFalse(service.validate(receipt))
        profiles.digest = "hmac-sha256:profiles-v1"
        identity.credential_id = "different-verifier"
        self.assertFalse(service.validate(receipt))

    def test_receipt_rejects_failed_profile(self):
        class _FailingRuntime(_Runtime):
            async def run_profile(self, **kwargs):
                return type("Result", (), {"exit_code": 1, "timed_out": False, "stdout": "", "stderr": "failed"})()

        service = GitVerificationService(
            _FailingRuntime(), _Profiles(), _VerifierIdentity(), signing_key=b"v" * 32
        )
        with self.assertRaisesRegex(RuntimeError, "Verification failed"):
            asyncio.run(service.verify(
                candidate_id="candidate-1", base_sha="base", tree_sha="tree",
                checks=("unit-tests",), project_root="C:/candidate",
            ))


class GitExecutionAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_capability_rejects_mutating_broker_actions(self):
        class Broker:
            def __init__(self):
                self.called = False

            def execute(self, *args, **kwargs):
                self.called = True
                raise AssertionError("mutating request reached the broker")

        broker = Broker()
        adapter = GitExecutionAdapter(broker, lambda *_args: True)
        call = CapabilityCall(
            capability_id="git.read",
            operation="read",
            project_root="C:/project",
            arguments={
                "request": {
                    "schema_version": 1,
                    "project_root": "C:/project",
                    "baseline_fingerprint": "sha256:baseline",
                    "actions": [{"kind": "apply_patch", "patch": "diff"}],
                },
                "model": "qwen",
                "grant_id": "grant-1",
            },
        )
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

        with self.assertRaisesRegex(PermissionError, "read-only"):
            async for _event in adapter.execute(call, context):
                pass
        self.assertFalse(broker.called)


if __name__ == "__main__":
    unittest.main()
