import json
import tempfile
import unittest
from pathlib import Path

from web_app.core.rea_provider_update_cli import discover_npm_release, provider_environment
from web_app.core.provider_compatibility import CompatibilityLayer, ProviderUpdateRequest
from web_app.core.rea_compatibility import ReaCompatibilityAdapter


class Completed:
    returncode = 0
    stdout = json.dumps({
        "version": "6.9.0",
        "dist.integrity": "sha512-real",
        "dist.tarball": "https://registry.npmjs.org/rea-agents/-/rea-agents-6.9.0.tgz",
    })
    stderr = ""


class ReaProviderUpdateCliTests(unittest.TestCase):
    def test_discovers_exact_release_identity_without_executing_package_code(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return Completed()

        metadata = discover_npm_release("6.9.0", runner=run)

        self.assertEqual(metadata.version, "6.9.0")
        self.assertEqual(metadata.integrity, "sha512-real")
        self.assertEqual(calls, [["npm.cmd", "view", "rea-agents@6.9.0", "version", "dist.integrity", "dist.tarball", "--json"]])

    def test_reuses_only_environment_from_manual_rea_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp_servers.json"
            path.write_text(json.dumps({"mcpServers": {"rea": {
                "command": "old.exe", "args": ["old.mjs", "mcp"],
                "env": {"JAVA_HOME": "D:/jdk", "TOKEN": "opaque"}, "allowedTools": ["*"]
            }}}), encoding="utf-8")

            environment = provider_environment(path)

            self.assertEqual(environment, {"JAVA_HOME": "D:/jdk", "TOKEN": "opaque"})

    def test_rea_adapter_maps_real_probe_evidence_into_shared_contract(self):
        async def updater(version, data_root, approved):
            return {
                "activation": {"version": version, "generation": 4},
                "evidence": {
                    "version": version, "harmless_tool": "inspect_analysis_settings",
                    "catalog_digest": "sha256:" + "a" * 64, "tool_count": 255,
                },
            }

        adapter = ReaCompatibilityAdapter(Path("D:/data"), updater)
        result = __import__("asyncio").run(CompatibilityLayer([adapter]).update(
            ProviderUpdateRequest(provider_id="rea", version="6.9.0")
        ))

        self.assertEqual(result.generation, 4)
        self.assertEqual(result.evidence.details["tool_count"], 255)


if __name__ == "__main__":
    unittest.main()
