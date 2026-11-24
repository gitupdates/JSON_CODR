import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

from web_app.core.autonomous_update import UpdateProfile
from web_app.core.update_launcher import (
    ActiveBuildPointer,
    ActiveBuildStore,
    ActivationError,
    CandidateHealthError,
    HealthReceipt,
    UpdateLauncher,
)
from web_app.version import APP_VERSION


class FakeProcess:
    def __init__(self, *, exit_code=None, pid=4321):
        self.pid = pid
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = 0

    def wait(self, timeout=None):
        return self.exit_code

    def kill(self):
        self.terminated = True
        self.exit_code = -9


class UpdateLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.candidate_root = self.root / "candidate"
        self.candidate_root.mkdir()
        self.revision = "a" * 40
        self.candidate = SimpleNamespace(
            candidate_id="candidate-1",
            commit_sha=self.revision,
            worktree=SimpleNamespace(working_root=str(self.candidate_root)),
        )
        self.profile = UpdateProfile(
            profile_id="self-update",
            repository_root=str(self.root),
            branch="main",
            mandatory_checks=("unit",),
            allowed_repository_roots=(str(self.root),),
            expected_version="V1.3.9",
            launch_argv=("python", "-m", "uvicorn", "web_app.app:app"),
            migration_compatibility="backward_compatible",
            startup_timeout_seconds=1,
        )
        self.processes = []
        self.environments = []

    def tearDown(self):
        self.temporary.cleanup()

    def process_factory(self, arguments, **kwargs):
        process = FakeProcess()
        self.processes.append(process)
        self.environments.append(dict(kwargs["env"]))
        return process

    def http_probe(self, url, timeout):
        if url.endswith("/api/health"):
            return {
                "status": "ready", "app_version": "V1.3.9", "revision": self.revision,
            }
        if url.endswith("/openapi.json"):
            return {"openapi": "3.1.0"}
        raise AssertionError(url)

    def launcher(self, **overrides):
        options = {
            "process_factory": self.process_factory,
            "http_probe": self.http_probe,
            "browser_probe": lambda _url: {"loaded": True, "fatal_errors": []},
            "port_allocator": lambda: 43210,
            "port_available": lambda _port: True,
            "sleep": lambda _seconds: None,
        }
        options.update(overrides)
        return UpdateLauncher(self.root / "launcher-state", **options)

    def test_launch_uses_disposable_data_and_exact_revision_version_environment(self):
        """Launching in the live data root or omitting exact identity must fail this test."""
        receipt = self.launcher().launch_candidate(self.candidate, self.profile)

        self.assertTrue(receipt.healthy)
        self.assertEqual(receipt.revision, self.revision)
        self.assertEqual(receipt.version, "V1.3.9")
        self.assertEqual(receipt.port, 43210)
        environment = self.environments[0]
        self.assertEqual(environment["JSON_CODR_REVISION"], self.revision)
        self.assertEqual(environment["JSON_CODR_EXPECTED_VERSION"], "V1.3.9")
        self.assertEqual(environment["JSON_CODR_DATA_ROOT"], receipt.data_root)
        self.assertTrue(Path(receipt.data_root).is_relative_to(self.root / "launcher-state"))

    def test_candidate_environment_excludes_parent_credentials_and_live_launcher_authority(self):
        with patch.dict(
            os.environ,
            {
                "GH_TOKEN": "candidate-must-not-inherit",
                "OPENAI_API_KEY": "candidate-must-not-inherit",
                "JSON_CODR_LAUNCHER_ROOT": str(self.root / "live-launcher"),
            },
        ):
            self.launcher().launch_candidate(self.candidate, self.profile)

        environment = self.environments[0]
        self.assertNotIn("GH_TOKEN", environment)
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("JSON_CODR_LAUNCHER_ROOT", environment)

    def test_version_mismatch_terminates_candidate_with_failure_receipt(self):
        """Accepting a process that reports another version must fail this test."""
        def wrong_version(url, timeout):
            result = self.http_probe(url, timeout)
            if url.endswith("/api/health"):
                result["app_version"] = "V9.9.9"
            return result

        with self.assertRaises(CandidateHealthError) as raised:
            self.launcher(http_probe=wrong_version).launch_candidate(self.candidate, self.profile)
        self.assertFalse(raised.exception.receipt.healthy)
        self.assertIn("version", raised.exception.receipt.error)
        self.assertTrue(self.processes[0].terminated)

    def test_unavailable_port_and_startup_failure_are_bounded(self):
        """Starting on an occupied port or waiting after child exit must fail this test."""
        with self.assertRaises(CandidateHealthError) as port_error:
            self.launcher(port_available=lambda _port: False).launch_candidate(
                self.candidate, self.profile
            )
        self.assertIn("port", port_error.exception.receipt.error)
        self.assertEqual(self.processes, [])

        def exited_factory(arguments, **kwargs):
            process = FakeProcess(exit_code=3)
            self.processes.append(process)
            return process

        with self.assertRaises(CandidateHealthError) as startup_error:
            self.launcher(process_factory=exited_factory).launch_candidate(
                self.candidate, self.profile
            )
        self.assertIn("exited", startup_error.exception.receipt.error)

    def test_api_failure_and_fatal_browser_errors_are_receipted(self):
        """A reachable process without required API/UI evidence must not become healthy."""
        with self.assertRaises(CandidateHealthError) as api_error:
            self.launcher(http_probe=lambda _url, _timeout: {}).launch_candidate(
                self.candidate, self.profile
            )
        self.assertIn("API", api_error.exception.receipt.error)

        browser = lambda _url: {
            "loaded": True,
            "fatal_errors": ["Uncaught TypeError: boot failed"],
        }
        with self.assertRaises(CandidateHealthError) as browser_error:
            self.launcher(browser_probe=browser).launch_candidate(self.candidate, self.profile)
        self.assertEqual(
            browser_error.exception.receipt.browser_fatal_errors,
            ("Uncaught TypeError: boot failed",),
        )

    def test_openapi_probe_retries_transient_startup_reset(self):
        """A live child must get the same bounded startup grace on every API probe."""
        openapi_attempts = 0

        def transient_openapi(url, timeout):
            nonlocal openapi_attempts
            if url.endswith("/openapi.json"):
                openapi_attempts += 1
                if openapi_attempts == 1:
                    raise ConnectionResetError("server is still accepting connections")
            return self.http_probe(url, timeout)

        receipt = self.launcher(http_probe=transient_openapi).launch_candidate(
            self.candidate, self.profile
        )

        self.assertTrue(receipt.healthy)
        self.assertEqual(openapi_attempts, 2)

    def test_incompatible_migration_is_blocked_before_process_start(self):
        """Unattended activation must never run an irreversible migration."""
        incompatible = self.profile.model_copy(update={"migration_compatibility": "irreversible"})
        with self.assertRaises(CandidateHealthError) as raised:
            self.launcher().launch_candidate(self.candidate, incompatible)
        self.assertIn("migration", raised.exception.receipt.error)
        self.assertEqual(self.processes, [])

    def test_pointer_write_interruption_keeps_previous_build(self):
        """Writing the active pointer in place would corrupt the known-good build here."""
        store = ActiveBuildStore(self.root / "pointer-state")
        previous = ActiveBuildPointer(
            revision="b" * 40, root=str(self.root / "previous"), version="V1.3.8",
            activated_at="2026-11-24T00:00:00+00:00", previous_revision=None,
        )
        store.write(previous)

        def interrupted(_source, _target):
            raise OSError("simulated pointer interruption")

        broken = ActiveBuildStore(self.root / "pointer-state", replacer=interrupted)
        with self.assertRaisesRegex(OSError, "interruption"):
            broken.write(previous.model_copy(update={"revision": self.revision}))
        self.assertEqual(store.load(), previous)

    def _healthy_receipt(self):
        return HealthReceipt(
            health_id="health-1", candidate_id="candidate-1", revision=self.revision,
            root=str(self.candidate_root), version="V1.3.9", host="127.0.0.1",
            port=43210, data_root=str(self.root / "disposable"), pid=4321,
            healthy=True, checks=("startup", "api", "openapi", "browser"),
            migration_compatibility="backward_compatible",
        )

    def test_post_switch_failure_automatically_restores_previous_pointer(self):
        """Leaving the failed candidate active after post-switch health must fail this test."""
        launcher = self.launcher(post_activation_probe=lambda _pointer, _receipt: False)
        previous = ActiveBuildPointer(
            revision="b" * 40, root=str(self.root / "previous"), version="V1.3.8",
            activated_at="2026-11-24T00:00:00+00:00", previous_revision=None,
        )
        launcher.pointer_store.write(previous)

        with self.assertRaises(ActivationError) as raised:
            launcher.activate(self._healthy_receipt())

        self.assertEqual(launcher.pointer_store.load().revision, previous.revision)
        self.assertEqual(raised.exception.rollback_receipt.restored_revision, previous.revision)

    def test_successful_activation_and_restart_safe_rollback(self):
        """Keeping rollback data only in process memory must fail this test."""
        launcher = self.launcher()
        previous = ActiveBuildPointer(
            revision="b" * 40, root=str(self.root / "previous"), version="V1.3.8",
            activated_at="2026-11-24T00:00:00+00:00", previous_revision=None,
        )
        launcher.pointer_store.write(previous)
        activation = launcher.activate(self._healthy_receipt())
        self.assertEqual(launcher.pointer_store.load().revision, self.revision)

        restarted = self.launcher()
        rollback = restarted.rollback(activation.activation_id)
        repeated = restarted.rollback(activation.activation_id)
        self.assertEqual(rollback, repeated)
        self.assertEqual(restarted.pointer_store.load().revision, previous.revision)

    def test_isolated_current_and_candidate_processes_activate_then_rollback(self):
        """Release proof uses two real loopback ports and never replaces the serving process."""
        server_source = '''
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

host, port, revision, version = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/health":
            payload = {"status": "ready", "revision": revision, "app_version": version}
            body = json.dumps(payload).encode()
            content_type = "application/json"
        elif self.path == "/openapi.json":
            body = json.dumps({"openapi": "3.1.0"}).encode()
            content_type = "application/json"
        elif self.path == "/":
            body = b"<!doctype html><title>isolated build</title>"
            content_type = "text/html"
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *_args): pass
ThreadingHTTPServer((host, port), Handler).serve_forever()
'''
        current_root = self.root / "current-build"
        candidate_root = self.root / "candidate-build"
        current_root.mkdir()
        candidate_root.mkdir()
        (current_root / "fixture_server.py").write_text(server_source, encoding="utf-8")
        (candidate_root / "fixture_server.py").write_text(server_source, encoding="utf-8")

        def available_port():
            with socket.socket() as stream:
                stream.bind(("127.0.0.1", 0))
                return stream.getsockname()[1]

        current_port = available_port()
        current_revision = "b" * 40
        candidate_revision = "c" * 40
        version = APP_VERSION
        current = subprocess.Popen(
            [sys.executable, "fixture_server.py", "127.0.0.1", str(current_port), current_revision, version],
            cwd=current_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        def browser_probe(base_url):
            deadline = time.monotonic() + 5
            while True:
                try:
                    with urlopen(base_url, timeout=0.5) as response:
                        return {"loaded": response.status == 200, "fatal_errors": ()}
                except OSError as error:
                    if time.monotonic() >= deadline:
                        return {"loaded": False, "fatal_errors": (str(error),)}
                    time.sleep(0.05)

        launcher = UpdateLauncher(self.root / "e2e-launcher", browser_probe=browser_probe)
        receipt = None
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{current_port}/api/health", timeout=0.5) as response:
                        self.assertEqual(json.loads(response.read())["revision"], current_revision)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        self.fail("current isolated build did not start")
                    time.sleep(0.05)
            launcher.pointer_store.write(ActiveBuildPointer(
                revision=current_revision, root=str(current_root), version=version,
                activated_at="2026-11-24T00:00:00+00:00", previous_revision=None,
            ))
            candidate = SimpleNamespace(
                candidate_id="candidate-e2e", commit_sha=candidate_revision,
                worktree=SimpleNamespace(working_root=str(candidate_root)),
            )
            profile = self.profile.model_copy(update={
                "expected_version": version,
                "launch_argv": (
                    sys.executable, "fixture_server.py", "{host}", "{port}",
                    candidate_revision, version,
                ),
                "startup_timeout_seconds": 10,
            })
            receipt = launcher.launch_candidate(candidate, profile)
            self.assertNotEqual(receipt.port, current_port)
            self.assertEqual(receipt.checks, ("startup", "api", "openapi", "browser"))
            activation = launcher.activate(receipt)
            self.assertEqual(launcher.pointer_store.load().revision, candidate_revision)

            restarted = UpdateLauncher(self.root / "e2e-launcher")
            rollback = restarted.rollback(activation.activation_id)
            self.assertEqual(rollback.restored_revision, current_revision)
            self.assertEqual(restarted.pointer_store.load().revision, current_revision)
        finally:
            if receipt is not None:
                launcher.terminate_health(receipt.health_id)
            if current.poll() is None:
                current.terminate()
                current.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
