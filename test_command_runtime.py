import sys
import tempfile
import unittest
from pathlib import Path

from web_app.core.command_runtime import CommandPolicy, CommandRuntime


class CommandRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_argv_sanitized_environment_redaction_and_declared_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = CommandPolicy(
                argv=(sys.executable, "-c", "print('token=very-secret')"),
                cwd=".", timeout_seconds=10,
            )
            result = await CommandRuntime().run_interactive_admin(
                policy, project_root=directory, administrator_scopes=("terminal.write",)
            )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("token=[REDACTED]", result.stdout)
        self.assertEqual(result.isolation_level, "output_bounded")
        self.assertNotIn("no_network", result.isolation_level)
        self.assertEqual(result.argv, policy.argv)

    async def test_escape_and_unapproved_environment_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = CommandRuntime()
            with self.assertRaisesRegex(ValueError, "escapes"):
                await runtime.run_interactive_admin(
                    CommandPolicy(argv=(sys.executable, "-V"), cwd=".."),
                    project_root=directory,
                    administrator_scopes=("terminal.write",),
                )
            with self.assertRaisesRegex(ValueError, "not allowed"):
                await runtime.run_interactive_admin(
                    CommandPolicy(argv=(sys.executable, "-V"), cwd=".", environment={"AWS_SECRET_ACCESS_KEY": "x"}),
                    project_root=directory,
                    administrator_scopes=("terminal.write",),
                )


if __name__ == "__main__":
    unittest.main()
