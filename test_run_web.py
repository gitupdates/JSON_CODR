import json
import os
import subprocess
import sys
import tempfile
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
        self.assertEqual(payload["version"], "V1.3.0")
        self.assertTrue(payload["python"])
        subprocess.run(
            [payload["python"], "-c", "from uuid import uuid7"],
            cwd=ROOT,
            check=True,
        )
        self.assertTrue(payload["compatiblePython"])
        compatible = subprocess.run(
            [
                payload["compatiblePython"],
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn(compatible.stdout.strip(), {"3.11", "3.12"})
        self.assertTrue(payload["ollama"])
        self.assertTrue(payload["supervised"])
        self.assertTrue(payload["ollamaNoCloud"])

    def test_launcher_is_valid_powershell(self):
        command = (
            "$errors=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{ROOT / 'run_web.ps1'}',"
            "[ref]$null,[ref]$errors)|Out-Null; if($errors.Count){exit 1}"
        )
        process = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command])
        self.assertEqual(process.returncode, 0)

    def test_launcher_prints_claim_only_while_bootstrap_is_pending(self):
        with tempfile.TemporaryDirectory() as data_root:
            unrelated_cwd = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = data_root
            environment["JSON_CODR_PYTHON"] = sys.executable
            repository_probe = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"], cwd=unrelated_cwd,
                capture_output=True, text=True, env=environment,
            )
            self.assertNotEqual(repository_probe.returncode, 0, repository_probe.stdout)
            pending = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "run_web.ps1"), "-BootstrapClaimOnly"],
                cwd=unrelated_cwd, capture_output=True, text=True, env=environment,
            )
            self.assertEqual(pending.returncode, 0, pending.stderr)
            marker = "Administrator bootstrap claim: "
            self.assertIn(marker, pending.stdout)
            claim = pending.stdout.split(marker, 1)[1].strip()
            claimed = subprocess.run(
                [sys.executable, "-c", "from web_app.security.accounts import AccountService; from web_app.security.bootstrap import BootstrapService; from web_app.security.passwords import PasswordHasher; from web_app.security.store import SecurityStore; from web_app.workspace import default_data_root; store=SecurityStore(default_data_root()/'security.sqlite3'); BootstrapService(store, AccountService(store, PasswordHasher())).claim_initial_administrator(__import__('os').environ['BOOTSTRAP_CLAIM'], 'Administrator', 'correct horse battery staple')"],
                cwd=ROOT, capture_output=True, text=True, env={**environment, "BOOTSTRAP_CLAIM": claim},
            )
            self.assertEqual(claimed.returncode, 0, claimed.stderr)
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "run_web.ps1"), "-BootstrapClaimOnly"],
                cwd=unrelated_cwd, capture_output=True, text=True, env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn(marker, completed.stdout)


if __name__ == "__main__":
    unittest.main()
