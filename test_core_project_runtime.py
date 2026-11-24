import subprocess
import tempfile
import unittest
from pathlib import Path

from web_app.core.adapters import CapabilityCall, ExecutionContext
from web_app.core.git_adapter import GitAdapter
from web_app.core.project_adapter import ProjectAdapter
from web_app.core.project_watch import ProjectWatcher
from web_app.core.terminal_adapter import TerminalAdapter
from web_app.git_broker import GitBrokerService


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return result.stdout.strip()


class FakeTerminalService:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []
        self.closed: list[str] = []

    def create(self, shell, cwd):
        return type("Record", (), {"id": "terminal-1", "pid": 42, "shell": shell, "cwd": str(cwd), "status": "running"})()

    def write(self, terminal_id, data):
        self.writes.append((terminal_id, data))

    def read_after(self, terminal_id, sequence, timeout=0.1):
        return [(sequence + 1, "output")]

    def close(self, terminal_id):
        self.closed.append(terminal_id)


class ProjectRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        (self.root / "file.txt").write_text("before", encoding="utf-8")
        self.context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

    async def asyncTearDown(self) -> None:
        self.temporary.cleanup()

    async def test_patch_creates_pre_edit_checkpoint_and_restores_exact_content(self):
        adapter = ProjectAdapter(Path(self.temporary.name) / "state")
        call = CapabilityCall(
            capability_id="project.patch",
            operation="replace",
            project_root=str(self.root),
            target_path=str(self.root / "file.txt"),
            arguments={"content": "after"},
        )

        events = [event async for event in adapter.execute(call, self.context)]
        checkpoint_id = events[0].payload["checkpoint_id"]
        self.assertEqual((self.root / "file.txt").read_text(encoding="utf-8"), "after")
        ProjectAdapter(Path(self.temporary.name) / "state").restore(checkpoint_id)
        self.assertEqual((self.root / "file.txt").read_text(encoding="utf-8"), "before")

    async def test_project_adapter_rejects_path_escape(self):
        adapter = ProjectAdapter(Path(self.temporary.name) / "state")
        call = CapabilityCall(
            capability_id="project.read",
            operation="read",
            project_root=str(self.root),
            target_path=str(self.root.parent / "outside.txt"),
        )
        with self.assertRaises(ValueError):
            _ = [event async for event in adapter.execute(call, self.context)]

    async def test_worktree_isolated_change_can_merge_with_evidence(self):
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Test")
        git(self.root, "add", "file.txt")
        git(self.root, "commit", "-m", "initial")
        adapter = GitAdapter(GitBrokerService(Path(self.temporary.name) / "broker-state"))
        worktree = Path(self.temporary.name) / "worktree"

        created = adapter.create_worktree(self.root, worktree, "agent-task-1", "task-1")
        (worktree / "file.txt").write_text("agent", encoding="utf-8")
        git(worktree, "add", "file.txt")
        git(worktree, "commit", "-m", "agent edit")
        merged = adapter.merge_worktree(self.root, created)

        self.assertEqual((self.root / "file.txt").read_text(encoding="utf-8"), "agent")
        self.assertEqual(merged.task_id, "task-1")
        self.assertTrue(merged.commit)

    def test_watcher_reports_external_change_with_fingerprints(self):
        watcher = ProjectWatcher(self.root)
        watcher.snapshot()
        (self.root / "file.txt").write_text("external", encoding="utf-8")

        event = watcher.poll()

        self.assertIsNotNone(event)
        self.assertNotEqual(event.before_fingerprint, event.after_fingerprint)
        self.assertIn("file.txt", event.changed_paths)

    async def test_terminal_session_is_attached_to_task_and_can_cancel(self):
        terminal = FakeTerminalService()
        adapter = TerminalAdapter(terminal)
        call = CapabilityCall(
            capability_id="terminal.execute",
            operation="test",
            project_root=str(self.root),
            arguments={"shell": "powershell", "command": "echo ok"},
        )

        events = [event async for event in adapter.execute(call, self.context)]
        adapter.cancel("terminal-1")

        self.assertEqual(events[0].payload["task_id"], "task-1")
        self.assertEqual(events[-1].payload["output"], "output")
        self.assertEqual(terminal.closed, ["terminal-1"])


if __name__ == "__main__":
    unittest.main()
