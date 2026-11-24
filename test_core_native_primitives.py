import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from web_app.core.adapters import CapabilityCall, ExecutionContext


class _TerminalService:
    def __init__(self) -> None:
        self.commands = []

    def create(self, shell, cwd):
        return type("Record", (), {"id": "term-1", "pid": 42, "shell": shell, "cwd": str(cwd), "status": "running"})()

    def write(self, terminal_id, text):
        self.commands.append((terminal_id, text))

    def read_after(self, terminal_id, sequence):
        return [(1, "verified\r\n")]


class NativePrimitiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / ".state"
        self.context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

    def tearDown(self):
        self.temporary.cleanup()

    def test_numbered_read_and_atomic_write_are_bounded(self):
        from web_app.core.project_adapter import ProjectAdapter

        project = ProjectAdapter(self.state)
        target = self.root / "sample.txt"
        target.write_text("one\ntwo\nthree\n", encoding="utf-8")

        self.assertEqual(project.read_lines(self.root, "sample.txt", (2, 3)), "2: two\n3: three")
        project.atomic_write(self.root, "sample.txt", "replacement\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "replacement\n")
        self.assertEqual(list(self.root.glob(".sample.txt.*.tmp")), [])
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            project.atomic_write(self.root, "large.txt", "x" * 1_048_577)

    def test_edit_requires_exact_context_and_creates_checkpoint(self):
        from web_app.core.project_adapter import ProjectAdapter

        project = ProjectAdapter(self.state)
        target = self.root / "sample.txt"
        target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        diff = "@@ -1,3 +1,3 @@\n alpha\n-beta\n+BETA\n gamma\n"

        record = project.apply_edit(self.root, "sample.txt", diff)

        self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nBETA\ngamma\n")
        self.assertTrue(Path(record.snapshot_path).is_file())
        with self.assertRaisesRegex(ValueError, "context"):
            project.apply_edit(self.root, "sample.txt", diff)

    def test_paths_cannot_escape_project_through_symlink(self):
        from web_app.core.project_adapter import ProjectAdapter

        outside = self.root.parent / f"{self.root.name}-outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.root / "escape.txt"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        self.addCleanup(outside.unlink, missing_ok=True)
        project = ProjectAdapter(self.state)

        with self.assertRaisesRegex(ValueError, "escapes"):
            project.read_lines(self.root, "escape.txt", None)

    async def test_adapter_exposes_exactly_four_native_capabilities(self):
        from web_app.core.native_primitives import NativePrimitiveAdapter
        from web_app.core.project_adapter import ProjectAdapter
        from web_app.core.terminal_adapter import TerminalAdapter

        terminal_service = _TerminalService()
        terminal = TerminalAdapter(terminal_service)
        from web_app.core.command_runtime import CommandResult
        commands = AsyncMock()
        commands.run.return_value = CommandResult(
            argv=("python", "-V"), cwd=str(self.root), exit_code=0,
            stdout="verified\n", stderr="", timed_out=False, truncated=False,
            isolation_level="test",
        )
        adapter = NativePrimitiveAdapter(ProjectAdapter(self.state), terminal, commands)
        (self.root / "source.txt").write_text("hello\n", encoding="utf-8")

        read = CapabilityCall(
            capability_id="native.read",
            operation="read",
            project_root=str(self.root),
            target_path="source.txt",
            arguments={"line_range": [1, 1]},
        )
        events = [event async for event in adapter.execute(read, self.context)]
        self.assertEqual(events[-1].event_type, "native.read.completed")
        self.assertEqual(events[-1].payload["content"], "1: hello")

        shell = CapabilityCall(
            capability_id="native.shell",
            operation="command",
            project_root=str(self.root),
            arguments={"argv": ["python", "-V"], "timeout": 15},
        )
        events = [event async for event in adapter.execute(shell, self.context)]
        self.assertEqual(events[0].payload["route"], "native")
        self.assertEqual(events[-1].payload["exit_code"], 0)
        commands.run.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
