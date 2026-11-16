import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from web_app.actions import ActionProposalService
from web_app.coding_agents import CodingAgentLaunchPlan
from web_app.models import ActionSuggestion
from web_app.terminal import TerminalService, child_environment


class TerminalServiceTests(unittest.TestCase):
    class FakePty:
        def __init__(self, argv, cwd, env, dimensions):
            self.argv = argv
            self.cwd = cwd
            self.env = env
            self.dimensions = dimensions
            self.pid = 77
            self.writes = []
            self.resizes = []
            self.closed = False
            self.alive = True
            self._output = []
            self._ready = threading.Condition()

        def read(self):
            with self._ready:
                self._ready.wait_for(lambda: self._output or not self.alive, timeout=1)
                if self._output:
                    return self._output.pop(0)
            raise EOFError

        def emit(self, text):
            with self._ready:
                self._output.append(text)
                self._ready.notify_all()

        def write(self, data):
            self.writes.append(data)

        def setwinsize(self, rows, cols):
            self.resizes.append((rows, cols))

        def sendintr(self):
            self.writes.append("\x03")

        def isalive(self):
            return self.alive

        def close(self, force=False):
            self.closed = True
            self.alive = False
            with self._ready:
                self._ready.notify_all()

    def test_child_environment_restores_windir_from_system_root(self):
        environment = child_environment({}, {"SystemRoot": r"C:\WINDOWS", "PATH": "test"})

        self.assertEqual(environment["windir"], r"C:\WINDOWS")
        self.assertEqual(environment["SystemRoot"], r"C:\WINDOWS")

    def test_interactive_agent_uses_embedded_conpty_when_available(self):
        created = []
        def factory(argv, cwd, env, dimensions):
            created.append(self.FakePty(argv, cwd, env, dimensions))
            return created[-1]
        plan = CodingAgentLaunchPlan(
            "continue",
            (r"C:\Users\BLACK\AppData\Roaming\npm\cn.CMD", "--model", "ollama/qwen:7b"),
            r"D:\project",
            {},
            True,
        )

        terminal = TerminalService(pty_factory=factory).create_agent(plan)

        self.assertFalse(terminal.external)
        self.assertEqual(terminal.backend, "conpty")
        self.assertEqual(created[0].argv, [
            r"C:\WINDOWS\system32\cmd.exe", "/d", "/s", "/c",
            r"C:\Users\BLACK\AppData\Roaming\npm\cn.CMD --model ollama/qwen:7b",
        ])

    def test_interactive_agent_falls_back_to_native_console_without_conpty(self):
        plan = CodingAgentLaunchPlan("aider", (r"C:\tools\aider.exe", "--model", "ollama_chat/qwen:7b"), r"D:\project", {}, True)

        with patch("web_app.terminal.subprocess.Popen") as popen:
            popen.return_value.pid = 43
            terminal = TerminalService(pty_factory=None).create_agent(plan)

        self.assertTrue(terminal.external)
        self.assertEqual(
            popen.call_args.args[0],
            [r"C:\tools\aider.exe", "--model", "ollama_chat/qwen:7b"],
        )

    def test_conpty_resize_and_reconnect_replay(self):
        created = []
        def factory(argv, cwd, env, dimensions):
            created.append(self.FakePty(argv, cwd, env, dimensions))
            return created[-1]

        with tempfile.TemporaryDirectory() as directory:
            service = TerminalService(pty_factory=factory, replay_limit=64)
            terminal = service.create("powershell", Path(directory), 100, 30)
            created[0].emit("first")
            created[0].emit("second")
            deadline = time.monotonic() + 2
            events = []
            while len(events) < 2 and time.monotonic() < deadline:
                events.extend(service.read_after(terminal.id, events[-1][0] if events else 0, timeout=0.2))

            self.assertEqual([event[1] for event in events], ["first", "second"])
            self.assertEqual(service.read_after(terminal.id, 0, timeout=0), events)
            service.resize(terminal.id, 132, 43)
            self.assertEqual(created[0].resizes, [(43, 132)])
            service.close(terminal.id)

    def test_close_all_stops_every_embedded_terminal(self):
        processes = []

        def factory(argv, cwd, env, dimensions):
            process = self.FakePty(argv, cwd, env, dimensions)
            processes.append(process)
            return process

        service = TerminalService(pty_factory=factory)
        service.create("powershell", Path.cwd())
        service.create("powershell", Path.cwd())

        service.close_all()

        self.assertTrue(all(process.closed for process in processes))
        self.assertEqual(service.list(), [])

    def test_persistent_powershell_streams_output_and_closes_exact_process(self):
        with tempfile.TemporaryDirectory() as directory:
            service = TerminalService()
            terminal = service.create("powershell", Path(directory), 100, 30)
            try:
                self.assertRegex(terminal.id, r"^[0-9a-f]{32}$")
                self.assertGreater(terminal.pid, 0)
                service.write(terminal.id, "Write-Output 'JSON_CODR_TERMINAL_READY'\r\n")

                deadline = time.monotonic() + 8
                output = ""
                while "JSON_CODR_TERMINAL_READY" not in output and time.monotonic() < deadline:
                    output += service.read(terminal.id, timeout=0.5)

                self.assertIn("JSON_CODR_TERMINAL_READY", output)
            finally:
                service.close(terminal.id)
            self.assertEqual(service.get(terminal.id).status, "closed")

    def test_unknown_terminal_id_is_rejected(self):
        with self.assertRaises(KeyError):
            TerminalService().write("0" * 32, "dir\r\n")

    def test_approved_action_uses_stored_command_and_exact_one_shot_token(self):
        with tempfile.TemporaryDirectory() as directory:
            service = TerminalService()
            approvals = ActionProposalService()
            terminal = service.create("powershell", Path(directory), 100, 30)
            try:
                proposal = approvals.propose(
                    "session",
                    [ActionSuggestion(
                        command="Write-Output 'JSON_CODR_APPROVED_ACTION'",
                        cwd=directory,
                        explanation="Test approved execution",
                    )],
                    ["pack:skill"],
                    directory,
                )[0]
                token = approvals.approve("session", proposal.id, terminal.id).token
                with self.assertRaises(PermissionError):
                    service.write_approved(terminal.id, approvals, proposal.id, "wrong-token")
                expected_marker = f"__JSON_CODR_ACTION_DONE__:{proposal.id}:"
                completion_marker = service.write_approved(
                    terminal.id, approvals, proposal.id, token, completion_marker=expected_marker
                )
                self.assertEqual(completion_marker, expected_marker)

                deadline = time.monotonic() + 8
                output = ""
                while f"{completion_marker}0" not in output and time.monotonic() < deadline:
                    output += service.read(terminal.id, timeout=0.5)
                self.assertIn("JSON_CODR_APPROVED_ACTION", output)
                self.assertIn(f"{completion_marker}0", output)
                with self.assertRaises(PermissionError):
                    service.write_approved(terminal.id, approvals, proposal.id, token)
            finally:
                service.close(terminal.id)


if __name__ == "__main__":
    unittest.main()
