import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.contracts import ProviderKind
from web_app.inference.environments import EnvironmentManager, find_compatible_python
from web_app.inference.sidecar import SidecarClient, SidecarError
from web_app.inference.sidecar_main import handle_request


class EnvironmentManagerTests(unittest.TestCase):
    def test_manager_construction_is_lazy_when_optional_python_is_absent(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "web_app.inference.environments.find_compatible_python",
            side_effect=RuntimeError("missing"),
        ) as resolver:
            manager = EnvironmentManager(Path(directory))

            self.assertEqual(manager.plan(ProviderKind.openvino).provider, ProviderKind.openvino)
            resolver.assert_not_called()

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
            self.assertIn("--require-hashes", install_command)
            self.assertIn("requirements-openvino-lock.txt", install_command)

    def test_provider_environment_uses_explicit_compatible_python_and_available_directml_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            compatible_python = Path("C:/Python312/python.exe")
            manager = EnvironmentManager(Path(directory), base_python=compatible_python)

            command = manager.install_command(ProviderKind.directml)

            self.assertIn("$rebuildProviderEnvironment = -not (Test-Path -LiteralPath", command)
            self.assertIn("if (-not $rebuildProviderEnvironment)", command)
            self.assertIn("sys.version_info[:2] not in ((3, 11), (3, 12))", command)
            self.assertIn(f'if ($rebuildProviderEnvironment) {{ & "{compatible_python}" -m venv --clear', command)
            self.assertIn("-m pip --disable-pip-version-check --no-input install", command)
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

    def test_verified_model_receipt_requires_exact_artifact_hashes_and_probe(self):
        import hashlib
        import json

        model = OptimizedModelCatalog().list()[0]
        with tempfile.TemporaryDirectory() as directory:
            manager = EnvironmentManager(Path(directory), base_python=Path("C:/Python312/python.exe"))
            target = manager.model_path(model)
            target.mkdir(parents=True)
            artifacts = []
            artifact_type = type(model.artifacts[0])
            for artifact in model.artifacts:
                payload = artifact.path.encode("utf-8")
                path = target / artifact.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                artifacts.append(artifact_type(
                    path=artifact.path,
                    size=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                ))
            local_model = model.model_copy(update={
                "maximum_download_bytes": 1_000_000,
                "artifacts": tuple(artifacts),
            })
            receipt = manager.verification_receipt_path(local_model)
            receipt.write_text(
                json.dumps(manager.verification_payload(local_model, probe_verified=False)),
                encoding="utf-8",
            )

            self.assertTrue(manager.verify_model(local_model, require_probe=False))
            self.assertFalse(manager.verify_model(local_model, require_probe=True))
            self.assertFalse(manager.model_ready(ProviderKind.openvino, (local_model,)))
            manager.mark_verified(local_model, {"device": "NPU", "probe": "OK"})
            self.assertTrue(manager.verify_model(local_model, require_probe=True))
            self.assertTrue(manager.model_ready(ProviderKind.openvino, (local_model,)))

            (target / artifacts[0].path).write_bytes(b"tampered")
            self.assertFalse(manager.verify_model(local_model, require_probe=True))
            self.assertFalse(manager.model_ready(ProviderKind.openvino, (local_model,)))

    def test_atomic_model_promotion_cleans_displaced_cache_and_restores_on_failure(self):
        import hashlib

        model = OptimizedModelCatalog().list()[0]
        artifact_type = type(model.artifacts[0])
        payload = b"verified model"
        local_model = model.model_copy(update={
            "maximum_download_bytes": 1_000_000,
            "artifacts": (artifact_type(
                path="openvino_model.bin",
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            ),),
        })

        def download(command, **kwargs):
            staging = Path(command[-1])
            staging.mkdir(parents=True)
            (staging / "openvino_model.bin").write_bytes(payload)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            manager = EnvironmentManager(Path(directory), base_python=Path("C:/Python312/python.exe"))
            manager.status = lambda provider: {"status": "ready"}
            target = manager.model_path(local_model)
            target.mkdir(parents=True)
            (target / "old.txt").write_text("old", encoding="utf-8")

            with patch("web_app.inference.environments.subprocess.run", side_effect=download):
                installed = manager.install_model(local_model)

            self.assertEqual(installed, target)
            self.assertEqual((target / "openvino_model.bin").read_bytes(), payload)
            self.assertFalse(list(target.parent.glob(".*.incomplete")))

        with tempfile.TemporaryDirectory() as directory:
            manager = EnvironmentManager(Path(directory), base_python=Path("C:/Python312/python.exe"))
            manager.status = lambda provider: {"status": "ready"}
            target = manager.model_path(local_model)
            target.mkdir(parents=True)
            original = target / "old.txt"
            original.write_text("restore me", encoding="utf-8")
            real_replace = os.replace

            def fail_promotion(source, destination):
                if Path(source).name.endswith(".staging") and Path(destination) == target:
                    raise OSError("promotion failed")
                return real_replace(source, destination)

            with patch("web_app.inference.environments.subprocess.run", side_effect=download), patch(
                "web_app.inference.environments.os.replace", side_effect=fail_promotion,
            ), self.assertRaisesRegex(OSError, "promotion failed"):
                manager.install_model(local_model)

            self.assertEqual(original.read_text(encoding="utf-8"), "restore me")
            self.assertFalse(list(target.parent.glob(".*.incomplete")))


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
