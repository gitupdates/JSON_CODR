import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from json_codr_launcher import LocalProcessRunner, load_pointer
from web_app.runtime_config import RuntimeConfig

ROOT = Path(__file__).resolve().parent


class RunWebTests(unittest.TestCase):
    def test_stable_launcher_refreshes_a_mutable_fallback_pointer_to_the_checked_out_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pointer_path = root / "launcher" / "pointer" / "active-build.json"
            first = load_pointer(
                pointer_path,
                fallback_root=str(root),
                fallback_revision="a" * 40,
                fallback_version="V1.4.0",
                data_root=str(root / "data"),
            )
            refreshed = load_pointer(
                pointer_path,
                fallback_root=str(root),
                fallback_revision="b" * 40,
                fallback_version="V1.4.1",
                data_root=str(root / "data"),
            )

        self.assertEqual(first["revision"], "a" * 40)
        self.assertEqual(refreshed["revision"], "b" * 40)
        self.assertEqual(refreshed["version"], "V1.4.1")
        self.assertEqual(refreshed["manifest_digest"], "fallback:" + "b" * 40)

    def test_local_launcher_propagates_unique_server_identity(self):
        pointer = {
            "root": str(ROOT),
            "revision": "c" * 40,
            "version": "V1.4.1",
            "data_root": str(ROOT / ".runtime-test-data"),
            "manifest_digest": "fallback:" + "c" * 40,
            "launch_argv": ["python", "-m", "uvicorn", "web_app.app:app", "--host", "{host}", "--port", "{port}"],
        }

        with patch("json_codr_launcher.subprocess.Popen") as popen:
            LocalProcessRunner().start(pointer, "127.0.0.1", 8765)

        environment = popen.call_args.kwargs["env"]
        self.assertEqual(environment["JSON_CODR_REVISION"], "c" * 40)
        self.assertEqual(environment["JSON_CODR_ARTIFACT_MANIFEST"], "fallback:" + "c" * 40)
        self.assertIn("JSON_CODR_INSTANCE_ID", environment)
        self.assertRegex(environment["JSON_CODR_INSTANCE_ID"], r"^active-[0-9a-f]{32}$")
        self.assertRegex(environment["JSON_CODR_STARTED_AT"], r"^2026-11-2[45]T")
        self.assertIn("JSON_CODR_SUPERVISOR_PID", environment)
        self.assertEqual(environment["JSON_CODR_SUPERVISOR_PID"], str(os.getpid()))

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
