import tempfile
import time
import unittest
from pathlib import Path

from web_app.terminal import TerminalService


class TerminalServiceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
