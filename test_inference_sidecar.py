import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from web_app.inference.contracts import ProviderKind
from web_app.inference.environments import EnvironmentManager, find_compatible_python
from web_app.inference.sidecar import SidecarClient, SidecarError
from web_app.inference.sidecar_main import handle_request


class EnvironmentManagerTests(unittest.TestCase):
    def test_configured_compatible_python_supports_a_newer_host_runtime(self):
        configured = Path("C:/configured/python.exe")

        with patch.dict(os.environ, {"JSON_CODR_COMPATIBLE_PYTHON": str(configured)}), patch(
            "web_app.inference.environments.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="3.12\n"),
        ):
            self.assertEqual(find_compatible_python(), configured)

    def test_provider_environments_are_isolated_and_install_plans_are_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = EnvironmentManager(Path(directory))
            plans = [manager.plan(provider) for provider in ProviderKind if provider is not ProviderKind.ollama]

            self.assertEqual(len({plan.root for plan in plans}), 4)
            self.assertTrue(all(plan.packages for plan in plans))
            self.assertTrue(all(any(character.isdigit() for character in " ".join(plan.packages)) for plan in plans))
            install_command = manager.install_command(ProviderKind.openvino)
            self.assertIn("-m venv", install_command)
            self.assertTrue(install_command.startswith('$providerPython = "'))

    def test_provider_environment_uses_explicit_compatible_python_and_available_directml_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            compatible_python = Path("C:/Python312/python.exe")
            manager = EnvironmentManager(Path(directory), base_python=compatible_python)

            command = manager.install_command(ProviderKind.directml)

            self.assertIn("$rebuildProviderEnvironment = -not (Test-Path -LiteralPath", command)
            self.assertIn("if (-not $rebuildProviderEnvironment)", command)
            self.assertIn("sys.version_info[:2] not in ((3, 11), (3, 12))", command)
            self.assertIn(f'if ($rebuildProviderEnvironment) {{ & "{compatible_python}" -m venv --clear', command)
            self.assertIn("-m pip --disable-pip-version-check install", command)
            self.assertIn("onnxruntime-genai-directml==0.12.2", command)

    def test_base_requirements_do_not_include_optional_runtimes(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("openvino", requirements)
        self.assertNotIn("onnxruntime", requirements)

    def test_provider_status_distinguishes_missing_and_compatible_environments(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = EnvironmentManager(Path(directory))
            missing = manager.status(ProviderKind.openvino)
            self.assertEqual(missing["status"], "missing")
            self.assertFalse(missing["installed"])

            plan = manager.plan(ProviderKind.openvino)
            plan.python.parent.mkdir(parents=True)
            plan.python.touch()
            manager._python_version = lambda python: (3, 12)
            manager._runtime_importable = lambda provider: True
            compatible = manager.status(ProviderKind.openvino)
            self.assertEqual(compatible["status"], "ready")
            self.assertTrue(compatible["compatible"])

    def test_compatible_python_without_provider_packages_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = EnvironmentManager(Path(directory))
            plan = manager.plan(ProviderKind.winml)
            plan.python.parent.mkdir(parents=True)
            plan.python.touch()
            manager._python_version = lambda python: (3, 12)
            manager._runtime_importable = lambda provider: False

            status = manager.status(ProviderKind.winml)

            self.assertEqual(status["status"], "incomplete")
            self.assertFalse(status["compatible"])


class SidecarClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdout_json_is_parsed_and_stderr_is_diagnostic_only(self):
        async def runner(command, request, timeout):
            return 0, '{"ok":true,"result":{"status":"ready"}}\n', "vendor warning"

        result = await SidecarClient(runner=runner).request("health", {}, 1)
        self.assertEqual(result, {"status": "ready"})

    async def test_exit_timeout_and_malformed_output_raise_typed_failures(self):
        responses = [
            (1, "", "crashed"),
            (0, "not-json", ""),
        ]

        async def runner(command, request, timeout):
            return responses.pop(0)

        client = SidecarClient(runner=runner)
        with self.assertRaisesRegex(SidecarError, "crashed"):
            await client.request("health", {}, 1)
        with self.assertRaisesRegex(SidecarError, "invalid JSON"):
            await client.request("health", {}, 1)

        async def timeout_runner(command, request, timeout):
            raise asyncio.TimeoutError

        with self.assertRaisesRegex(SidecarError, "timed out"):
            await SidecarClient(runner=timeout_runner).request("health", {}, 1)

    async def test_sidecar_dispatches_chat_and_benchmark_to_provider_handler(self):
        calls = []

        def handler(operation, payload):
            calls.append((operation, payload))
            return {"status": "ok"}

        response = handle_request(
            {"operation": "chat", "payload": {"provider": "openvino", "prompt": "hello"}},
            {"openvino": handler},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["result"], {"status": "ok"})
        self.assertEqual(calls, [("chat", {"provider": "openvino", "prompt": "hello"})])


if __name__ == "__main__":
    unittest.main()
