import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from web_app.core.command_runtime import CommandPolicy, CommandRuntime, _WindowsJob
from web_app.core.verification_profiles import VerificationProfile, VerificationProfileStore


class _Administrator:
    roles = ("administrator",)
    scopes = ("verification.profiles.manage",)
    credential_id = "credential-1"
    authentication_source = "browser_session"


def _resolve_administrator(token, *, required_scope):
    if token != "admin-token" or required_scope != "verification.profiles.manage":
        raise PermissionError("invalid administrator credential")
    return _Administrator()


class CommandRuntimeProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = VerificationProfileStore(
            self.root / "data",
            administration_resolver=_resolve_administrator,
            integrity_key=b"profile-integrity-test-key",
        )
        self.store.replace((
            VerificationProfile(
                profile_id="python-version",
                executable=sys.executable,
                argument_template=("-c", "import sys; print(sys.argv[1])", "{value:token}"),
                cwd_rule="project_root",
                timeout_seconds=10,
                max_output_bytes=4096,
                network_policy="allow",
            ),
        ), credential="admin-token")

    def tearDown(self):
        self.temporary.cleanup()

    async def test_profile_execution_rejects_raw_argv_and_uses_typed_values(self):
        """Replacing the profile route with arbitrary argv must fail this test."""
        runtime = CommandRuntime(self.store)
        with self.assertRaisesRegex(ValueError, "raw argv"):
            await runtime.run_profile(
                profile_id="python-version",
                values={"value": "safe"},
                raw_argv=(sys.executable, "-c", "print('unsafe')"),
                project_root=self.root,
            )

        result = await runtime.run_profile(
            profile_id="python-version", values={"value": "safe"}, project_root=self.root
        )
        self.assertEqual(result.stdout.strip(), "safe")
        self.assertEqual(result.argv[0], sys.executable)

    async def test_raw_interactive_execution_requires_administrator_terminal_scope(self):
        """Dropping the administrator scope guard must fail this test."""
        with self.assertRaisesRegex(PermissionError, "administrator"):
            await CommandRuntime().run_interactive_admin(
                CommandPolicy(argv=(sys.executable, "-V"), cwd="."),
                project_root=self.root,
                administrator_scopes=(),
            )

    async def test_profile_execution_rejects_interpreters_absolute_values_and_environment(self):
        """Relaxing the profile input boundary must fail this test."""
        runtime = CommandRuntime(self.store)
        for values in (
            {"value": r"C:\\Windows\\System32\\cmd.exe"},
            {"value": r"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"},
            {"value": str(self.root.resolve())},
        ):
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, "path|interpreter"):
                    await runtime.run_profile(profile_id="python-version", values=values, project_root=self.root)
        with self.assertRaisesRegex(ValueError, "environment"):
            await runtime.run_profile(
                profile_id="python-version",
                values={"value": "safe"},
                environment={"AWS_SECRET_ACCESS_KEY": "x"},
                project_root=self.root,
            )

    async def test_no_network_profile_is_rejected_without_an_enforcing_adapter(self):
        """Claiming no-network isolation from a Boolean policy must fail this test."""
        self.store.replace((
            VerificationProfile(
                profile_id="network-probe",
                executable=sys.executable,
                argument_template=("-c", "import urllib.request; urllib.request.urlopen(sys.argv[1])", "{url:token}"),
                cwd_rule="project_root",
                timeout_seconds=10,
                max_output_bytes=4096,
                network_policy="deny",
            ),
        ), credential="admin-token")
        with self.assertRaisesRegex(ValueError, "network"):
            await CommandRuntime(self.store).run_profile(
                profile_id="network-probe", values={"url": "https://example.invalid"}, project_root=self.root
            )

    async def test_profile_values_cannot_escape_or_follow_outside_links(self):
        """Candidate-controlled path spellings and reparse targets must fail this test."""
        runtime = CommandRuntime(self.store)
        hostile_values = (
            r"..\outside",
            r"C:\outside",
            r"C:outside",
            r"--config=C:\outside",
            "--config=outside-link",
            "@outside-link",
            "../outside",
        )
        for value in hostile_values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "path|escape"):
                    await runtime.run_profile(
                        profile_id="python-version", values={"value": value}, project_root=self.root
                    )

        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        link = self.root / "outside-link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink or junction creation is unavailable")
        self.addCleanup(outside.rmdir)
        self.store.replace((
            VerificationProfile(
                profile_id="project-path",
                executable=sys.executable,
                argument_template=("-c", "print('unused')", "--config={config:project_path}"),
                cwd_rule="project_root",
                timeout_seconds=10,
                max_output_bytes=4096,
                network_policy="allow",
            ),
        ), credential="admin-token")
        with self.assertRaisesRegex(ValueError, "escape"):
            await runtime.run_profile(
                profile_id="project-path", values={"config": "outside-link"}, project_root=self.root
            )

    async def test_profile_output_is_streamed_with_a_hard_memory_limit(self):
        """Buffering the complete child output before truncation must fail this test."""
        self.store.replace((
            VerificationProfile(
                profile_id="large-output",
                executable=sys.executable,
                argument_template=("-c", "import sys; sys.stdout.write('x' * 200000)"),
                cwd_rule="project_root",
                timeout_seconds=10,
                max_output_bytes=4096,
                network_policy="allow",
            ),
        ), credential="admin-token")
        result = await CommandRuntime(self.store).run_profile(
            profile_id="large-output", values={}, project_root=self.root
        )
        self.assertEqual(len(result.stdout.encode("utf-8")), 4096)
        self.assertTrue(result.truncated)
        self.assertEqual(result.isolation_level, "output_bounded")

    async def test_timeout_terminates_descendant_process_tree(self):
        """A timed-out verifier descendant must not survive to mutate the project."""
        sentinel = self.root / "descendant-survived.txt"
        child = (
            "import pathlib,time; time.sleep(2); "
            f"pathlib.Path({str(sentinel)!r}).write_text('escaped', encoding='utf-8')"
        )
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
        )
        self.store.replace((
            VerificationProfile(
                profile_id="timeout-tree",
                executable=sys.executable,
                argument_template=("-c", parent),
                cwd_rule="project_root",
                timeout_seconds=1,
                max_output_bytes=4096,
                network_policy="allow",
            ),
        ), credential="admin-token")
        result = await CommandRuntime(self.store).run_profile(
            profile_id="timeout-tree", values={}, project_root=self.root
        )
        self.assertTrue(result.timed_out)
        await asyncio.sleep(2.5)
        self.assertFalse(sentinel.exists())

    @unittest.skipUnless(os.name == "nt", "Windows taskkill fallback behavior")
    async def test_taskkill_failure_is_reported_after_fallback_kill(self):
        """A nonzero taskkill result must not be silently treated as cleanup success."""
        process = MagicMock()
        process.pid = 1234
        process.returncode = None
        process.wait = AsyncMock()
        with patch.object(CommandRuntime, "_taskkill_tree", new=AsyncMock(return_value=False)):
            with self.assertRaisesRegex(RuntimeError, "process tree"):
                await CommandRuntime._terminate_process_tree(process, windows_job=None)
        process.kill.assert_called_once()

    async def test_timeout_terminates_descendant_after_parent_has_exited(self):
        """A verifier child must be cleaned even after its direct parent exits."""
        sentinel = self.root / "parent-exited-descendant.txt"
        child = (
            "import pathlib,time; time.sleep(2); "
            f"pathlib.Path({str(sentinel)!r}).write_text('escaped', encoding='utf-8')"
        )
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(0.2)"
        )
        self.store.replace((
            VerificationProfile(
                profile_id="parent-exited-tree",
                executable=sys.executable,
                argument_template=("-c", parent),
                cwd_rule="project_root",
                timeout_seconds=1,
                max_output_bytes=4096,
                network_policy="allow",
            ),
        ), credential="admin-token")
        result = await CommandRuntime(self.store).run_profile(
            profile_id="parent-exited-tree", values={}, project_root=self.root
        )
        self.assertTrue(result.timed_out)
        await asyncio.sleep(2.5)
        self.assertFalse(sentinel.exists())

    @unittest.skipUnless(os.name == "nt", "Windows suspended launch behavior")
    async def test_process_cannot_spawn_before_job_assignment(self):
        """A fast verifier must remain suspended until its enforcing job is assigned."""
        sentinel = self.root / "pre-assignment-escape.txt"
        child = (
            "import pathlib,time; time.sleep(0.2); "
            f"pathlib.Path({str(sentinel)!r}).write_text('escaped', encoding='utf-8')"
        )
        parent = (
            "import subprocess,sys; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)"
        )
        self.store.replace((
            VerificationProfile(
                profile_id="assignment-race",
                executable=sys.executable,
                argument_template=("-c", parent),
                cwd_rule="project_root",
                timeout_seconds=5,
                max_output_bytes=4096,
                network_policy="allow",
            ),
        ), credential="admin-token")
        original_init = _WindowsJob.__init__

        def delayed_assignment(job, process_id):
            time.sleep(0.5)
            original_init(job, process_id)

        with patch.object(_WindowsJob, "__init__", delayed_assignment):
            result = await CommandRuntime(self.store).run_profile(
                profile_id="assignment-race", values={}, project_root=self.root
            )
        self.assertEqual(result.exit_code, 0)
        await asyncio.sleep(0.5)
        self.assertFalse(sentinel.exists())

    @unittest.skipUnless(os.name == "nt", "Windows Job Object close behavior")
    async def test_normal_parent_completion_closes_job_and_kills_redirected_descendant(self):
        """A descendant with redirected I/O must not outlive a normally completed verifier."""
        sentinel = self.root / "normal-parent-descendant.txt"
        child = (
            "import pathlib,time; time.sleep(1); "
            f"pathlib.Path({str(sentinel)!r}).write_text('escaped', encoding='utf-8')"
        )
        parent = (
            "import subprocess,sys; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)"
        )
        self.store.replace((
            VerificationProfile(
                profile_id="normal-parent-tree",
                executable=sys.executable,
                argument_template=("-c", parent),
                cwd_rule="project_root",
                timeout_seconds=5,
                max_output_bytes=4096,
                network_policy="allow",
            ),
        ), credential="admin-token")
        result = await CommandRuntime(self.store).run_profile(
            profile_id="normal-parent-tree", values={}, project_root=self.root
        )
        self.assertEqual(result.exit_code, 0)
        await asyncio.sleep(1.5)
        self.assertFalse(sentinel.exists())
