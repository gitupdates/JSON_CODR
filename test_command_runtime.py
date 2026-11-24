import asyncio
import os
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

    @unittest.skipUnless(os.name == "nt", "Windows detached-process behavior")
    async def test_interactive_admin_detached_child_survives_parent_completion(self):
        """Applying verifier Job containment to interactive commands must fail this test."""
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "interactive-detached-child.txt"
            child = (
                "import pathlib,time; time.sleep(0.5); "
                f"pathlib.Path({str(sentinel)!r}).write_text('survived', encoding='utf-8')"
            )
            parent = (
                "import subprocess,sys; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}], "
                "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, "
                "close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)"
            )
            result = await CommandRuntime().run_interactive_admin(
                CommandPolicy(argv=(sys.executable, "-c", parent), cwd=".", timeout_seconds=5),
                project_root=directory,
                administrator_scopes=("terminal.write",),
            )
            self.assertEqual(result.exit_code, 0)
            for _ in range(40):
                if sentinel.exists():
                    break
                await asyncio.sleep(0.05)
            self.assertTrue(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
