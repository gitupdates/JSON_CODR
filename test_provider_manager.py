import tempfile
import unittest
from pathlib import Path

from web_app.core.credentials import CredentialBroker
from web_app.core.provider_manager import ProviderManager
from web_app.core.provider_protocol import ProviderManifest


class FakeClient:
    def __init__(self, probe_ok=True):
        self.probe_ok = probe_ok
        self.calls = []
        self.cancelled = []

    async def request(self, operation, payload, timeout=120):
        self.calls.append((operation, payload))
        if operation == "probe":
            return {"ready": self.probe_ok}
        return {"ok": True, "operation": operation}

    async def cancel(self, call_id):
        self.cancelled.append(call_id)


class ProviderManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_selects_supported_interpreter_and_requires_functional_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = []
            client = FakeClient()

            def resolve(versions):
                selected.append(versions)
                return Path("C:/Python312/python.exe")

            def install(manifest, target, python):
                target.mkdir(parents=True)
                (target / "installed.txt").write_text(str(python), encoding="utf-8")

            manager = ProviderManager(Path(directory), resolve, install, lambda process: client)
            manifest = ProviderManifest(
                provider_id="mcp", version="1.0", python_versions=("3.12", "3.14"),
                packages={"mcp": "sha256:" + "1" * 64}, probe_operation="probe",
            )

            process = await manager.ensure(manifest)

            self.assertEqual(selected, [("3.12", "3.14")])
            self.assertEqual(process.python, "C:\\Python312\\python.exe")
            self.assertTrue(process.ready)
            self.assertTrue((Path(directory) / "mcp" / "provider-lock.json").is_file())

    async def test_failed_upgrade_rolls_back_and_optional_provider_failure_is_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            good_client = FakeClient()
            clients = [good_client, FakeClient(probe_ok=False)]

            def install(manifest, target, python):
                target.mkdir(parents=True)

            manager = ProviderManager(
                Path(directory), lambda versions: Path("C:/Python312/python.exe"), install,
                lambda process: clients.pop(0),
            )
            first = ProviderManifest(
                provider_id="openvino", version="1.0", python_versions=("3.12",),
                packages={"openvino": "sha256:" + "2" * 64}, probe_operation="probe",
            )
            await manager.ensure(first)
            second = first.model_copy(update={"version": "2.0"})

            with self.assertRaisesRegex(RuntimeError, "functional probe"):
                await manager.ensure(second)

            self.assertEqual(manager.lock("openvino").version, "1.0")
            self.assertTrue((Path(directory) / "openvino").is_dir())

    async def test_execution_cancellation_and_credentials_do_not_persist_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            credentials = CredentialBroker()
            reference = credentials.put("github", "top-secret")
            client = FakeClient()

            def install(manifest, target, python):
                target.mkdir(parents=True)

            manager = ProviderManager(
                Path(directory), lambda versions: Path("C:/Python312/python.exe"), install,
                lambda process: client, credentials=credentials,
            )
            manifest = ProviderManifest(
                provider_id="git-tools", version="1.0", python_versions=("3.12",),
                packages={"git-tools": "sha256:" + "3" * 64}, probe_operation="probe",
            )
            await manager.ensure(manifest)

            result = await manager.execute("git-tools", "call-1", "inspect", {"credential_refs": [reference]})
            await manager.cancel("call-1")
            credentials.revoke(reference)

            self.assertTrue(result["ok"])
            self.assertEqual(client.cancelled, ["call-1"])
            self.assertNotIn("top-secret", (Path(directory) / "git-tools" / "provider-lock.json").read_text())
            with self.assertRaises(KeyError):
                credentials.resolve_for_adapter(reference)


if __name__ == "__main__":
    unittest.main()
