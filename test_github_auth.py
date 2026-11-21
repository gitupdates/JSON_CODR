import subprocess
import threading
import time
import unittest

from web_app.github_auth import (
    GitHubAuthSessionConflict,
    GitHubAuthSessionNotFound,
    GitHubAuthSessionService,
)


class _Input:
    def __init__(self):
        self.value = ""

    def write(self, value):
        self.value += value

    def flush(self):
        return None


class _BlockingOutput:
    def __init__(self, lines=()):
        self._lines = list(lines)
        self._released = threading.Event()

    def __iter__(self):
        yield from self._lines
        self._released.wait(2)

    def release(self):
        self._released.set()


class _Process:
    def __init__(self, lines=(), returncode=None):
        self.stdin = _Input()
        self.stdout = _BlockingOutput(lines)
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        deadline = time.monotonic() + (timeout or 2)
        while self.returncode is None and time.monotonic() < deadline:
            time.sleep(0.005)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("gh", timeout)
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self.stdout.release()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.stdout.release()

    def finish(self, returncode=0):
        self.returncode = returncode
        self.stdout.release()


def _wait_for(service, session_id, state):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        result = service.status(session_id)
        if result["state"] == state:
            return result
        time.sleep(0.01)
    raise AssertionError(f"session did not reach {state}: {service.status(session_id)}")


class GitHubAuthSessionTests(unittest.TestCase):
    def test_start_uses_github_web_flow_and_rejects_duplicate_active_login(self):
        calls = []
        process = _Process()

        def factory(arguments, **kwargs):
            calls.append((arguments, kwargs))
            return process

        service = GitHubAuthSessionService(
            executable_finder=lambda name: "gh.exe",
            process_factory=factory,
            status_probe=lambda: {"authenticated": True},
            poll_interval=0.005,
        )
        started = service.start()
        self.assertEqual(started["state"], "starting")
        self.assertEqual(
            calls[0][0],
            ["gh.exe", "auth", "login", "--web", "--hostname", "github.com", "--git-protocol", "https"],
        )
        self.assertFalse(calls[0][1]["shell"])
        with self.assertRaises(GitHubAuthSessionConflict):
            service.start()
        service.cancel(started["session_id"])
        self.assertTrue(process.terminated)

    def test_waiting_exposes_only_device_code_and_cancel_terminates_process(self):
        process = _Process([
            "authentication token ghp_123456789012345678901234567890\n",
            "First copy your one-time code: ABCD-1234\n",
        ])
        service = GitHubAuthSessionService(
            executable_finder=lambda name: "gh.exe",
            process_factory=lambda *args, **kwargs: process,
            status_probe=lambda: {"authenticated": False},
            poll_interval=0.005,
        )
        session_id = service.start()["session_id"]
        waiting = _wait_for(service, session_id, "waiting")
        self.assertEqual(waiting["device_code"], "ABCD-1234")
        self.assertEqual(waiting["verification_url"], "https://github.com/login/device")
        self.assertNotIn("ghp_", repr(waiting))
        cancelled = service.cancel(session_id)
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertTrue(process.terminated)

    def test_success_failure_timeout_close_and_retention_are_bounded(self):
        successful = _Process(["Opening github.com in your browser.\n"])
        service = GitHubAuthSessionService(
            executable_finder=lambda name: "gh.exe",
            process_factory=lambda *args, **kwargs: successful,
            status_probe=lambda: {"authenticated": True, "login": "octocat"},
            poll_interval=0.005,
            retention_seconds=0.1,
        )
        success_id = service.start()["session_id"]
        successful.finish(0)
        authenticated = _wait_for(service, success_id, "authenticated")
        self.assertEqual(authenticated["login"], "octocat")
        time.sleep(0.12)
        with self.assertRaises(GitHubAuthSessionNotFound):
            service.status(success_id)

        failed = _Process(["failed with ghp_123456789012345678901234567890\n"])
        service = GitHubAuthSessionService(
            executable_finder=lambda name: "gh.exe",
            process_factory=lambda *args, **kwargs: failed,
            status_probe=lambda: {"authenticated": False},
            poll_interval=0.005,
        )
        failed_id = service.start()["session_id"]
        failed.finish(1)
        failure = _wait_for(service, failed_id, "failed")
        self.assertNotIn("ghp_", failure["detail"])

        timed = _Process()
        service = GitHubAuthSessionService(
            executable_finder=lambda name: "gh.exe",
            process_factory=lambda *args, **kwargs: timed,
            status_probe=lambda: {"authenticated": False},
            timeout=0.02,
            poll_interval=0.005,
        )
        timed_id = service.start()["session_id"]
        self.assertEqual(_wait_for(service, timed_id, "expired")["state"], "expired")
        self.assertTrue(timed.terminated)

        active = _Process()
        service = GitHubAuthSessionService(
            executable_finder=lambda name: "gh.exe",
            process_factory=lambda *args, **kwargs: active,
            status_probe=lambda: {"authenticated": False},
            poll_interval=0.005,
        )
        active_id = service.start()["session_id"]
        service.close()
        self.assertEqual(service.status(active_id)["state"], "cancelled")
        self.assertTrue(active.terminated)

    def test_missing_github_cli_fails_without_starting_a_session(self):
        service = GitHubAuthSessionService(executable_finder=lambda name: None)
        with self.assertRaisesRegex(RuntimeError, "GitHub CLI is not installed"):
            service.start()

    def test_cancel_during_blocked_status_probe_cannot_be_overwritten_by_success(self):
        process = _Process(["Authentication complete.\n"])
        probe_started = threading.Event()
        release_probe = threading.Event()

        def blocked_probe():
            probe_started.set()
            release_probe.wait(2)
            return {"authenticated": True, "login": "octocat"}

        service = GitHubAuthSessionService(
            executable_finder=lambda name: "gh.exe",
            process_factory=lambda *args, **kwargs: process,
            status_probe=blocked_probe,
            poll_interval=0.005,
        )
        session_id = service.start()["session_id"]
        process.finish(0)
        self.assertTrue(probe_started.wait(1))
        service.cancel(session_id)
        release_probe.set()
        time.sleep(0.03)
        self.assertEqual(service.status(session_id)["state"], "cancelled")
        service.close()


if __name__ == "__main__":
    unittest.main()
