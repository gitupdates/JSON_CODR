import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from web_app.actions import ActionProposalService
from web_app.coding_agents import CodingAgentLaunchPlan
from web_app.models import ActionSuggestion
from web_app.terminal import TerminalService, child_environment


class TerminalServiceTests(unittest.TestCase):
    def test_child_environment_restores_windir_from_system_root(self):
        environment = child_environment({}, {"SystemRoot": r"C:\WINDOWS", "PATH": "test"})

        self.assertEqual(environment["windir"], r"C:\WINDOWS")
        self.assertEqual(environment["SystemRoot"], r"C:\WINDOWS")

    @patch("web_app.terminal.subprocess.Popen")
    def test_interactive_agent_opens_native_windows_console(self, popen):
        popen.return_value.pid = 42
        plan = CodingAgentLaunchPlan(
            "continue",
            (r"C:\Users\BLACK\AppData\Roaming\npm\cn.CMD", "--model", "ollama/qwen:7b"),
            r"D:\project",
            {},
            True,
        )

        terminal = TerminalService().create_agent(plan)

        self.assertTrue(terminal.external)
        self.assertEqual(terminal.status, "external")
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], [
            r"C:\WINDOWS\system32\cmd.exe", "/d", "/s", "/c",
            r"C:\Users\BLACK\AppData\Roaming\npm\cn.CMD --model ollama/qwen:7b",
        ])
        self.assertEqual(
            popen.call_args.kwargs["creationflags"],
            subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    @patch("web_app.terminal.subprocess.Popen")
    def test_interactive_executable_launches_directly_in_native_console(self, popen):
        popen.return_value.pid = 43
        plan = CodingAgentLaunchPlan("aider", (r"C:\tools\aider.exe", "--model", "ollama_chat/qwen:7b"), r"D:\project", {}, True)

        TerminalService().create_agent(plan)

        self.assertEqual(
            popen.call_args.args[0],
            [r"C:\tools\aider.exe", "--model", "ollama_chat/qwen:7b"],
        )

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
                while completion_marker not in output and time.monotonic() < deadline:
                    output += service.read(terminal.id, timeout=0.5)
                self.assertIn("JSON_CODR_APPROVED_ACTION", output)
                self.assertIn(f"{completion_marker}0", output)
                with self.assertRaises(PermissionError):
                    service.write_approved(terminal.id, approvals, proposal.id, token)
            finally:
                service.close(terminal.id)


if __name__ == "__main__":
    unittest.main()
