import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.environments import PACKAGES


ROOT = Path(__file__).resolve().parent


class IntelNpuBootstrapPolicyTests(unittest.TestCase):
    def test_accelerator_manifest_matches_the_runtime_catalog_and_exact_packages(self):
        policy = json.loads((ROOT / "config" / "bootstrap-accelerators.json").read_text(encoding="utf-8"))
        provider = policy["providers"][0]
        model = OptimizedModelCatalog().list()[0]

        self.assertEqual(provider["condition"], "intel_npu")
        self.assertFalse(provider["installs_driver"])
        self.assertEqual(provider["lockfile"], "requirements-openvino-lock.txt")
        lock_text = (ROOT / provider["lockfile"]).read_text(encoding="utf-8")
        self.assertIn("--hash=sha256:", lock_text)
        self.assertIn("hf-xet==1.8.0 --hash=sha256:", lock_text)
        self.assertNotRegex(lock_text, r"(?m)^\s*[^#\s].*(?:>=|~=|<)")
        self.assertEqual(provider["model"]["id"], model.id)
        self.assertEqual(provider["model"]["repository"], model.repository)
        self.assertEqual(provider["model"]["revision"], model.revision)
        self.assertEqual(provider["model"]["maximum_download_bytes"], model.maximum_download_bytes)
        self.assertEqual(provider["model"]["artifacts"], [item.model_dump(mode="json") for item in model.artifacts])
        self.assertEqual(provider["packages"], list(PACKAGES[model.provider]))

    def test_disabled_intel_condition_skips_provider_python_install(self):
        command = (
            f"Import-Module '{ROOT / 'scripts' / 'bootstrap' / 'Manifest.psm1'}' -Force; "
            f"Import-Module '{ROOT / 'scripts' / 'bootstrap' / 'Planner.psm1'}' -Force; "
            f"$manifest=Import-JsonCodrBootstrapManifest -Root '{ROOT}'; "
            f"Get-JsonCodrBootstrapPlan -Manifest $manifest -Root '{ROOT}' -Conditions @{{intel_npu=$false}} | ConvertTo-Json -Depth 8 -Compress"
        )
        process = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=dict(os.environ),
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        plan = json.loads(process.stdout)
        provider_python = next(item for item in plan["components"] if item["id"] == "python-openvino")
        self.assertEqual(provider_python["action"], "skip")
        self.assertEqual(provider_python["condition"], "intel_npu")

    def test_hardware_gate_requires_healthy_intel_npu_and_never_mentions_driver_install(self):
        module = ROOT / "scripts" / "bootstrap" / "Accelerator.psm1"
        command = (
            f"Import-Module '{module}' -Force; "
            "$records=@("
            "[pscustomobject]@{Name='Intel(R) AI Boost';Status='OK';ConfigManagerErrorCode=0},"
            "[pscustomobject]@{Name='Intel NPU';Status='Error';ConfigManagerErrorCode=10},"
            "[pscustomobject]@{Name='NVIDIA GPU';Status='OK';ConfigManagerErrorCode=0}); "
            "Get-JsonCodrIntelNpuHardware -DeviceRecords $records | ConvertTo-Json -Depth 5 -Compress"
        )
        process = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        hardware = json.loads(process.stdout)
        self.assertTrue(hardware["detected"])
        self.assertEqual(hardware["devices"], ["Intel(R) AI Boost"])
        self.assertNotIn("install driver", hardware["detail"].casefold())

    def test_optional_winget_failure_does_not_block_required_bootstrap(self):
        module = ROOT / "scripts" / "bootstrap" / "Install.psm1"
        with tempfile.TemporaryDirectory() as directory:
            fake_winget = Path(directory) / "winget.exe"
            shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe", fake_winget)
            environment = dict(os.environ)
            environment["PATH"] = f"{directory}{os.pathsep}{environment.get('PATH', '')}"

            def invoke(condition):
                serialized_condition = "$null" if condition is None else f"'{condition}'"
                command = (
                    f"Import-Module '{module}' -Force; "
                    "$component=[pscustomobject]@{id='python-openvino';package='Python.Python.3.12';"
                    "command='python3.12.exe';action='install';version_selector='-3.12';"
                    f"condition={serialized_condition}}}; "
                    "$plan=[pscustomobject]@{components=@($component)}; "
                    "Invoke-JsonCodrInstallPlan -Plan $plan"
                )
                return subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    cwd=ROOT,
                    env=environment,
                )

            optional = invoke("intel_npu")
            required = invoke(None)

        self.assertEqual(optional.returncode, 0, optional.stderr)
        self.assertIn("Optional prerequisite python-openvino was not installed", optional.stderr)
        self.assertNotEqual(required.returncode, 0)
        self.assertIn("prerequisite python-openvino", required.stderr)


if __name__ == "__main__":
    unittest.main()
