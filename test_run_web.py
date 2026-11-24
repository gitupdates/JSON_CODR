import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from web_app.runtime_config import RuntimeConfig

ROOT = Path(__file__).resolve().parent


class RunWebTests(unittest.TestCase):
    def test_launcher_validation_reports_localhost_runtime(self):
        config = RuntimeConfig.load()
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
        self.assertEqual(payload["host"], config.host)
        self.assertEqual(payload["port"], config.port)
        self.assertEqual(payload["url"], config.url)
        self.assertEqual(payload["version"], config.version)
        self.assertEqual(payload["healthPath"], config.health_path)
        self.assertEqual(payload["runtimeStatusPath"], config.runtime_status_path)
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
        self.assertTrue(payload["stableLauncher"])
        self.assertTrue(Path(payload["activeBuildPointer"]).is_absolute())

    def test_stable_launcher_and_web_controller_share_the_live_data_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = dict(os.environ)
            environment["JSON_CODR_DATA_ROOT"] = temporary
            environment.pop("JSON_CODR_LAUNCHER_ROOT", None)
            process = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(ROOT / "run_web.ps1"), "-ValidateOnly",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(process.stdout)
            data_root = Path(temporary).resolve()
            self.assertEqual(Path(payload["dataRoot"]), data_root)
            self.assertEqual(
                Path(payload["activeBuildPointer"]),
                data_root / "launcher" / "pointer" / "active-build.json",
            )

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
