import asyncio
import tempfile
import unittest
from pathlib import Path

from web_app.inference.contracts import ProviderKind
from web_app.inference.environments import EnvironmentManager
from web_app.inference.sidecar import SidecarClient, SidecarError
from web_app.inference.sidecar_main import handle_request


class EnvironmentManagerTests(unittest.TestCase):
    def test_provider_environments_are_isolated_and_install_plans_are_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = EnvironmentManager(Path(directory))
            plans = [manager.plan(provider) for provider in ProviderKind if provider is not ProviderKind.ollama]

            self.assertEqual(len({plan.root for plan in plans}), 4)
            self.assertTrue(all(plan.packages for plan in plans))
            self.assertTrue(all(any(character.isdigit() for character in " ".join(plan.packages)) for plan in plans))
            self.assertIn("-m venv", manager.install_command(ProviderKind.openvino))

    def test_base_requirements_do_not_include_optional_runtimes(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("openvino", requirements)
        self.assertNotIn("onnxruntime", requirements)


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
