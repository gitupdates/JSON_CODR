import os
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from web_app.core.autonomous_update import UpdateProfile
from web_app.core.canonical import canonical_digest
from web_app.core.git_adapter import VerificationReceipt
from web_app.core.update_launcher import (
    ArtifactMaterializer,
    BuildManifestSigner,
    CandidateHealthError,
    HealthReceiptSigner,
    UpdateLauncher,
)


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout.strip()


class FakeProcess:
    def __init__(self):
        self.container_id = "container-1"
        self.exit_code = None
        self.terminated = False
        self.pid = None

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = 0

    def wait(self, timeout=None):
        return self.exit_code or 0

    def kill(self):
        self.terminated = True
        self.exit_code = -9


class FakeIsolationRunner:
    def __init__(self):
        self.calls = []
        self.processes = []

    def launch(self, **values):
        self.calls.append(values)
        process = FakeProcess()
        self.processes.append(process)
        return process

    def resolve_image(self, _image):
        return "sha256:" + "c" * 64


class FakeSupervisor:
    def __init__(self):
        self.activations = []
        self.rollbacks = []

    def activate(self, health, target):
        self.activations.append((health, target))
        return {
            "activation_id": "activation-1",
            "health_id": health.health_id,
            "revision": health.revision,
            "previous_revision": "previous",
            "status": "activated",
        }

    def rollback(self, activation_id):
        self.rollbacks.append(activation_id)
        return {
            "rollback_id": "rollback-1", "activation_id": activation_id,
            "restored_revision": "previous", "status": "rolled_back",
        }


class UpdateLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "candidate"
        self.repository.mkdir()
        git(self.repository, "init", "-b", "main")
        git(self.repository, "config", "user.name", "JSON CODR Tests")
        git(self.repository, "config", "user.email", "tests@example.invalid")
        (self.repository / "web_app").mkdir()
        (self.repository / "web_app" / "version.py").write_text(
            'APP_VERSION = "V1.3.9"\n', encoding="utf-8"
        )
        (self.repository / "server.py").write_text("print('fixture')\n", encoding="utf-8")
        git(self.repository, "add", ".")
        git(self.repository, "commit", "-m", "candidate")
        self.revision = git(self.repository, "rev-parse", "HEAD")
        self.tree = git(self.repository, "rev-parse", f"{self.revision}^{{tree}}")
        self.profile = UpdateProfile(
            profile_id="self-update",
            repository_root=str(self.repository),
            branch="main",
            expected_remote_sha=self.revision,
            mandatory_checks=("unit",),
            allowed_repository_roots=(str(self.repository),),
            expected_version="V1.3.9",
            launch_argv=("python3", "server.py", "{host}", "{port}"),
            container_image="fixture-image:locked",
            container_port=8000,
            migration_compatibility="backward_compatible",
            startup_timeout_seconds=1,
        )
        profile_digest = canonical_digest(self.profile.model_dump(mode="json"))
        self.candidate = SimpleNamespace(
            candidate_id="candidate-1",
            commit_sha=self.revision,
            profile_digest=profile_digest,
            verification_receipt=VerificationReceipt(
                candidate_id="candidate-1", base_sha=self.revision,
                tree_sha=self.tree, profile_digest="sha256:" + "a" * 64,
                checks=("unit",), verified_at=datetime.now(UTC),
                verifier_credential_id="verifier", signature="hmac-sha256:" + "b" * 64,
            ),
            worktree=SimpleNamespace(working_root=str(self.repository)),
        )
        self.isolation = FakeIsolationRunner()
        self.supervisor = FakeSupervisor()
        self.key = b"k" * 32
        self.browser_errors = []

    def tearDown(self):
        self.temporary.cleanup()

    def http_probe(self, url, timeout, headers=None):
        if url.endswith("/openapi.json"):
            return {"openapi": "3.1.0"}
        environment = self.isolation.calls[-1]["environment"]
        return {
            "status": "ready",
            "app_version": environment["JSON_CODR_EXPECTED_VERSION"],
            "revision": environment["JSON_CODR_REVISION"],
            "health_nonce": dict(headers or {}).get("X-JSON-CODR-Health-Nonce"),
            "instance_id": environment["JSON_CODR_INSTANCE_ID"],
            "started_at": environment["JSON_CODR_STARTED_AT"],
            "manifest_digest": environment["JSON_CODR_ARTIFACT_MANIFEST"],
        }

    def launcher(self, **overrides):
        values = {
            "materializer": ArtifactMaterializer(self.root / "artifacts"),
            "isolation_runner": self.isolation,
            "manifest_signer": BuildManifestSigner(key=self.key),
            "health_signer": HealthReceiptSigner(self.key),
            "supervisor_client": self.supervisor,
            "http_probe": self.http_probe,
            "browser_probe": lambda _url: {
                "loaded": True, "fatal_errors": tuple(self.browser_errors),
            },
            "port_allocator": lambda: 43210,
            "port_available": lambda _port: True,
            "sleep": lambda _seconds: None,
        }
        values.update(overrides)
        return UpdateLauncher(self.root / "launcher", **values)

    def test_health_uses_immutable_artifact_restricted_environment_and_signed_fresh_receipt(self):
        with patch.dict(os.environ, {"GH_TOKEN": "secret", "OPENAI_API_KEY": "secret"}):
            launcher = self.launcher()
            receipt = launcher.launch_candidate(self.candidate, self.profile)

        call = self.isolation.calls[0]
        environment = call["environment"]
        self.assertTrue(receipt.healthy)
        self.assertEqual(receipt.tree_sha, self.tree)
        self.assertEqual(receipt.isolation, "docker-restricted")
        self.assertTrue(HealthReceiptSigner(self.key).validate(receipt))
        self.assertFalse((Path(receipt.root) / ".git").exists())
        self.assertEqual(Path(call["artifact_root"]), Path(receipt.root))
        self.assertEqual(environment["JSON_CODR_DATA_ROOT"], "/data")
        self.assertNotIn("GH_TOKEN", environment)
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertIn("fresh-liveness", receipt.checks)

    def test_missing_container_image_fails_closed_before_launch(self):
        profile = self.profile.model_copy(update={"container_image": None})
        candidate = SimpleNamespace(**{
            **self.candidate.__dict__,
            "profile_digest": canonical_digest(profile.model_dump(mode="json")),
        })
        with self.assertRaisesRegex(CandidateHealthError, "container image"):
            self.launcher().launch_candidate(candidate, profile)
        self.assertEqual(self.isolation.calls, [])

    def test_replayed_health_nonce_terminates_container(self):
        def replay(url, timeout, headers=None):
            value = self.http_probe(url, timeout, headers)
            if url.endswith("/api/health"):
                value["health_nonce"] = "old-nonce"
            return value

        with self.assertRaisesRegex(CandidateHealthError, "fresh health"):
            self.launcher(http_probe=replay).launch_candidate(self.candidate, self.profile)
        self.assertTrue(self.isolation.processes[0].terminated)

    def test_activation_reprobes_then_delegates_switch_to_stable_supervisor(self):
        launcher = self.launcher()
        health = launcher.launch_candidate(self.candidate, self.profile)

        activation = launcher.activate(health)

        self.assertEqual(activation["status"], "activated")
        self.assertEqual(len(self.supervisor.activations), 1)
        target = self.supervisor.activations[0][1]
        self.assertEqual(target["runner"], "docker")
        self.assertEqual(target["tree_sha"], self.tree)
        self.assertEqual(target["manifest_digest"], health.manifest_digest)
        self.assertTrue(self.isolation.processes[0].terminated)

    def test_stale_or_tampered_health_receipt_cannot_activate(self):
        launcher = self.launcher()
        health = launcher.launch_candidate(self.candidate, self.profile)
        stale = HealthReceiptSigner(self.key).sign(
            health.model_copy(update={"fresh_until": datetime.now(UTC) - timedelta(seconds=1)})
        )
        with self.assertRaisesRegex(PermissionError, "stale"):
            launcher.activate(stale)
        with self.assertRaisesRegex(PermissionError, "signature"):
            launcher.activate(health.model_copy(update={"version": "V9.9.9"}))

    def test_browser_error_fails_health_and_close_cleans_successful_processes(self):
        self.browser_errors.append("fatal console")
        with self.assertRaisesRegex(CandidateHealthError, "browser"):
            self.launcher().launch_candidate(self.candidate, self.profile)
        self.assertTrue(self.isolation.processes[-1].terminated)

        self.browser_errors.clear()
        launcher = self.launcher()
        launcher.launch_candidate(self.candidate, self.profile)
        launcher.close()
        self.assertTrue(self.isolation.processes[-1].terminated)

    def test_rollback_is_owned_by_stable_supervisor(self):
        receipt = self.launcher().rollback("activation-1")
        self.assertEqual(receipt["status"], "rolled_back")
        self.assertEqual(self.supervisor.rollbacks, ["activation-1"])


if __name__ == "__main__":
    unittest.main()
