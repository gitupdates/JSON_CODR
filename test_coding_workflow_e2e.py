import asyncio
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from web_app.core.command_runtime import CommandPolicy, CommandRuntime
from web_app.core.project_adapter import ProjectAdapter
from web_app.github_cli import GitHubCLI


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()


def repository(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    git(project, "init", "-b", "main")
    git(project, "config", "user.name", "JSON CODR Verifier")
    git(project, "config", "user.email", "verifier@example.invalid")
    git(project, "remote", "add", "origin", "https://github.com/json-codr-verifier/disposable.git")
    (project / "README.md").write_text("initial\n", encoding="utf-8")
    git(project, "add", "README.md")
    git(project, "commit", "-m", "initial")
    return project


class DisposableWorkflowSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_delivery_script_has_a_bounded_receipt_and_cleanup_contract(self):
        script = Path("scripts/verify-coding-workflow.ps1")

        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        for evidence in (
            "checkpoint.restore",
            "native.edit",
            "CommandRuntime",
            "/api/github/local/commit",
            "model_digest",
            "disposed",
        ):
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, text)
        self.assertLess(
            text.index("'--literal-pathspecs', 'add'"),
            text.index("'diff', '--cached'"),
        )
        self.assertIn("__pycache__/", text)

    def test_local_commit_does_not_execute_repository_hooks(self):
        project = repository(self.root)
        sentinel = self.root / "hook-escaped.txt"
        hook = project / ".git" / "hooks" / "pre-commit"
        hook.write_text(
            "#!/bin/sh\nprintf escaped > \"" + sentinel.as_posix() + "\"\n",
            encoding="utf-8",
        )
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        (project / "change.txt").write_text("change\n", encoding="utf-8")
        git(project, "add", "change.txt")

        GitHubCLI(executable_finder=shutil.which).commit_local_changes(
            str(project), "verified change"
        )

        self.assertFalse(sentinel.exists())

    def test_crafted_filename_is_staged_as_data(self):
        project = repository(self.root)
        crafted = "--upload-pack=owned path.txt"
        (project / crafted).write_text("data\n", encoding="utf-8")

        def runner(arguments, **kwargs):
            if Path(arguments[0]).stem.casefold() == "gh":
                return subprocess.CompletedProcess(
                    arguments, 0, '{"permissions":{"push":false}}', ""
                )
            return subprocess.run(arguments, **kwargs)

        client = GitHubCLI(executable_finder=shutil.which, runner=runner)
        client.stage_local_files(str(project), [crafted])

        self.assertEqual(git(project, "diff", "--cached", "--name-only"), crafted)

    def test_link_escape_is_rejected(self):
        project = self.root / "project"
        outside = self.root / "outside"
        project.mkdir()
        outside.mkdir()
        link = project / "escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory links are unavailable: {error}")

        adapter = ProjectAdapter(self.root / "state")
        with self.assertRaisesRegex(ValueError, "escapes"):
            adapter.atomic_write(project, "escape/owned.txt", "owned\n")
        self.assertFalse((outside / "owned.txt").exists())

    def test_rollback_rejects_a_target_changed_after_the_checkpointed_edit(self):
        project = self.root / "project"
        project.mkdir()
        target = project / "value.txt"
        target.write_text("before\n", encoding="utf-8")
        adapter = ProjectAdapter(self.root / "state")
        checkpoint = adapter.atomic_write(project, "value.txt", "approved\n")
        target.write_text("drifted\n", encoding="utf-8")

        with self.assertRaisesRegex(PermissionError, "changed|mismatch"):
            adapter.restore(checkpoint.checkpoint_id)

        self.assertEqual(target.read_text(encoding="utf-8"), "drifted\n")


class DisposableWorkflowCommandBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_environment_injection_is_rejected_before_process_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / "environment-escaped.txt"
            policy = CommandPolicy(
                argv=(
                    shutil.which("python") or "python",
                    "-c",
                    "import os,pathlib; pathlib.Path('environment-escaped.txt').write_text(os.environ.get('AWS_SECRET_ACCESS_KEY','missing'))",
                ),
                cwd=".",
                environment={"AWS_SECRET_ACCESS_KEY": "owned"},
            )

            with self.assertRaisesRegex(ValueError, "environment key"):
                await CommandRuntime().run_interactive_admin(
                    policy,
                    project_root=root,
                    administrator_scopes=("terminal.write",),
                )

            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
