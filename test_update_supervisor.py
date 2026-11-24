import json
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from json_codr_launcher import (
    ActivationSwitchError,
    DockerPublicRunner,
    PointerStore,
    StableSupervisor,
    SupervisorControl,
    _signature,
    health_receipt_validator,
)
from web_app.core.update_launcher import FileSupervisorClient


class FakeChild:
    def __init__(self, revision):
        self.revision = revision
        self.stopped = False


class FakeRunner:
    def __init__(self):
        self.started = []
        self.stopped = []

    def start(self, pointer, host, port):
        child = FakeChild(pointer["revision"])
        self.started.append((dict(pointer), host, port, child))
        return child

    def stop(self, child):
        child.stopped = True
        self.stopped.append(child.revision)


def pointer(revision, generation=0):
    return {
        "schema_version": 1,
        "generation": generation,
        "revision": revision,
        "tree_sha": revision,
        "root": f"C:/immutable/{revision[:8]}",
        "version": "V1.3.9",
        "runner": "docker",
        "launch_argv": ["fixture-server", revision],
        "manifest_digest": "sha256:" + revision,
        "manifest_signature": "hmac-sha256:" + revision,
        "artifact_digest": "d" * 64,
        "container_image": "sha256:" + "c" * 64,
        "container_port": 8000,
        "data_root": f"C:/data/{revision[:8]}",
        "activated_at": "2026-11-24T00:00:00+00:00",
        "previous_revision": None,
    }


def health(target, **updates):
    value = {
        "signed": True,
        "healthy": True,
        "isolation": "docker-restricted",
        "revision": target["revision"],
        "tree_sha": target["tree_sha"],
        "root": target["root"],
        "version": target["version"],
        "manifest_digest": target["manifest_digest"],
        "manifest_signature": target["manifest_signature"],
        "artifact_digest": target["artifact_digest"],
        "container_image": target["container_image"],
        "container_port": target["container_port"],
    }
    value.update(updates)
    return value


class StableSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.synced = []
        self.store = PointerStore(
            self.root / "active-build.json",
            directory_sync=lambda path: self.synced.append(Path(path)),
        )
        self.runner = FakeRunner()
        self.probe_revisions = set()

        def probe(_host, _port, expected_revision):
            return expected_revision in self.probe_revisions

        self.supervisor = StableSupervisor(
            self.store,
            runner=self.runner,
            probe=probe,
            host="127.0.0.1",
            port=54321,
            receipt_validator=lambda receipt: receipt.get("signed") is True,
        )

    def tearDown(self):
        self.supervisor.shutdown()
        self.temporary.cleanup()

    def test_initial_known_good_pointer_is_persisted_and_parent_is_synced(self):
        initial = pointer("a" * 40)
        self.probe_revisions.add(initial["revision"])

        active = self.supervisor.initialize(initial)

        self.assertEqual(active["revision"], initial["revision"])
        self.assertEqual(self.store.load()["revision"], initial["revision"])
        self.assertTrue(self.store.load()["known_good"])
        self.assertIn(self.store.pointer_path.parent, self.synced)

    def test_supervisor_owns_cas_switch_and_replaces_public_child(self):
        initial = pointer("a" * 40)
        target = pointer("b" * 40)
        self.probe_revisions.update((initial["revision"], target["revision"]))
        self.supervisor.initialize(initial)

        receipt = self.supervisor.activate({
            "activation_id": "activation-1",
            "expected_generation": 0,
            "target_pointer": target,
            "health_receipt": health(target),
        })

        self.assertEqual(receipt["status"], "activated")
        self.assertEqual(self.store.load()["revision"], target["revision"])
        self.assertEqual(self.store.load()["generation"], 1)
        self.assertTrue(self.runner.started[0][3].stopped)
        self.assertFalse(self.runner.started[-1][3].stopped)
        self.assertFalse(self.store.journal_path.exists())

    def test_failed_immediate_public_probe_restores_previous_child_and_pointer(self):
        initial = pointer("a" * 40)
        target = pointer("b" * 40)
        self.probe_revisions.add(initial["revision"])
        self.supervisor.initialize(initial)

        with self.assertRaises(ActivationSwitchError) as raised:
            self.supervisor.activate({
                "activation_id": "activation-failed",
                "expected_generation": 0,
                "target_pointer": target,
                "health_receipt": health(target),
            })

        self.assertEqual(raised.exception.rollback_receipt["restored_revision"], initial["revision"])
        self.assertEqual(self.store.load()["revision"], initial["revision"])
        self.assertEqual(self.runner.started[-1][0]["revision"], initial["revision"])
        self.assertFalse(self.runner.started[-1][3].stopped)

    def test_startup_recovers_incomplete_pointer_commit_to_previous_known_good(self):
        previous = pointer("a" * 40)
        target = pointer("b" * 40, generation=1)
        self.store.ensure_known_good(previous)
        self.store.compare_and_swap(0, target)
        self.store.write_journal({
            "operation": "activate",
            "phase": "pointer_committed",
            "activation_id": "activation-crashed",
            "previous_pointer": previous,
            "target_pointer": target,
        })
        self.probe_revisions.add(previous["revision"])

        recovered = self.supervisor.initialize(previous)

        self.assertEqual(recovered["revision"], previous["revision"])
        self.assertEqual(self.store.load()["revision"], previous["revision"])
        self.assertEqual(self.store.load()["generation"], 2)
        self.assertFalse(self.store.journal_path.exists())

    def test_pointer_compare_and_swap_rejects_stale_activation(self):
        initial = pointer("a" * 40)
        self.store.ensure_known_good(initial)
        self.store.compare_and_swap(0, pointer("b" * 40))

        with self.assertRaisesRegex(RuntimeError, "generation"):
            self.store.compare_and_swap(0, pointer("c" * 40))

        self.assertEqual(self.store.load()["revision"], "b" * 40)

    def test_control_loop_authenticates_request_and_owns_generation_selection(self):
        initial = pointer("a" * 40)
        target = pointer("b" * 40)
        self.probe_revisions.update((initial["revision"], target["revision"]))
        self.supervisor.initialize(initial)
        key = b"s" * 32
        control = SupervisorControl(self.root / "control", self.supervisor, key=key)
        request = {
            "request_id": "request-1",
            "operation": "activate",
            "payload": {
                "activation_id": "activation-control",
                "target_pointer": target,
                "health_receipt": health(target),
            },
            "issued_at": "2026-11-24T00:00:00+00:00",
        }
        request["signature"] = _signature(key, request)
        (control.requests / "request-1.json").write_text(json.dumps(request), encoding="utf-8")

        self.assertTrue(control.process_once())

        response = json.loads((control.responses / "request-1.json").read_text(encoding="utf-8"))
        self.assertTrue(response["ok"])
        self.assertEqual(self.store.load()["generation"], 1)
        self.assertEqual(self.store.load()["revision"], target["revision"])

    def test_file_client_and_stdlib_supervisor_interoperate_with_signed_ipc(self):
        initial = pointer("a" * 40)
        target = pointer("b" * 40)
        self.probe_revisions.update((initial["revision"], target["revision"]))
        self.supervisor.initialize(initial)
        key = b"i" * 32
        control = SupervisorControl(self.root / "control-ipc", self.supervisor, key=key)
        client = FileSupervisorClient(control.root, key=key, timeout_seconds=5)

        def process_request():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if control.process_once():
                    return
                time.sleep(0.01)

        thread = threading.Thread(target=process_request)
        thread.start()
        result = client._submit("activate", {
            "activation_id": "activation-ipc",
            "target_pointer": target,
            "health_receipt": health(target),
        })
        thread.join(5)

        self.assertEqual(result["status"], "activated")
        self.assertEqual(self.store.load()["revision"], target["revision"])

    def test_signed_health_validator_rejects_tamper_and_expiry(self):
        key = b"h" * 32
        receipt = health(pointer("a" * 40),
            fresh_until=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        )
        receipt["signature"] = _signature(key, receipt)
        validate = health_receipt_validator(key)

        self.assertTrue(validate(receipt))
        self.assertFalse(validate({**receipt, "version": "V9.9.9"}))
        expired = {**receipt, "fresh_until": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
        expired["signature"] = _signature(key, expired)
        self.assertFalse(validate(expired))

    def test_public_docker_runner_has_restricted_mount_and_user_boundary(self):
        calls = []

        def run(arguments, **kwargs):
            calls.append(list(arguments))
            if "wslpath" in arguments:
                return subprocess.CompletedProcess(arguments, 0, "/isolated/path\n", "")
            if "run" in arguments:
                return subprocess.CompletedProcess(arguments, 0, "container-id\n", "")
            if "inspect" in arguments:
                return subprocess.CompletedProcess(arguments, 0, "sha256:" + "c" * 64 + "\n", "")
            return subprocess.CompletedProcess(arguments, 0, "ok\n", "")

        artifact = self.root / "artifact"
        data = self.root / "data"
        artifact.mkdir()
        data.mkdir()
        target = pointer("d" * 40)
        target.update({"root": str(artifact), "data_root": str(data)})
        target["artifact_digest"] = __import__("hashlib").sha256().hexdigest()
        runner = DockerPublicRunner(command_runner=run)

        child = runner.start(target, "127.0.0.1", 54321)

        docker_run = next(call for call in calls if "run" in call)
        flattened = " ".join(docker_run)
        self.assertIn("--read-only", docker_run)
        self.assertIn("65534:65534", docker_run)
        self.assertIn("no-new-privileges", flattened)
        self.assertIn("/isolated/path:/app:ro", docker_run)
        self.assertEqual(child.container_id, "container-id")


if __name__ == "__main__":
    unittest.main()
