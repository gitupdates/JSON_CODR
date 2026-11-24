import sys
import tempfile
import unittest
from pathlib import Path

from web_app.core.command_runtime import CommandPolicy, CommandRuntime
from web_app.core.verification_profiles import VerificationProfile, VerificationProfileStore


class CommandRuntimeProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = VerificationProfileStore(self.root / "data")
        self.store.replace((
            VerificationProfile(
                profile_id="python-version",
                executable=sys.executable,
                argument_template=("-c", "import sys; print(sys.argv[1])", "{value}"),
                cwd_rule="project_root",
                timeout_seconds=10,
                max_output_bytes=4096,
                network_policy="allow",
            ),
        ), scopes=("verification.profiles.manage",))

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
                with self.assertRaisesRegex(ValueError, "absolute path|interpreter"):
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
                argument_template=("-c", "import urllib.request; urllib.request.urlopen({url!r})"),
                cwd_rule="project_root",
                timeout_seconds=10,
                max_output_bytes=4096,
                network_policy="deny",
            ),
        ), scopes=("verification.profiles.manage",))
        with self.assertRaisesRegex(ValueError, "network"):
            await CommandRuntime(self.store).run_profile(
                profile_id="network-probe", values={"url": "https://example.invalid"}, project_root=self.root
            )
