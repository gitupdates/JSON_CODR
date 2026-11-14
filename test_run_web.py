import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class RunWebTests(unittest.TestCase):
    def test_launcher_validation_reports_localhost_runtime(self):
        process = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "run_web.ps1"),
                "-ValidateOnly",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertEqual(payload["host"], "127.0.0.1")
        self.assertEqual(payload["port"], 8765)
        self.assertEqual(payload["url"], "http://127.0.0.1:8765")
        self.assertEqual(payload["version"], "V1.0.4")
        self.assertTrue(payload["python"])
        self.assertTrue(payload["ollama"])

    def test_launcher_is_valid_powershell(self):
        command = (
            "$errors=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{ROOT / 'run_web.ps1'}',"
            "[ref]$null,[ref]$errors)|Out-Null; if($errors.Count){exit 1}"
        )
        process = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command])
        self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
