import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from web_app.core.rea_provider_state import ReaProviderStore
from web_app.core.rea_verification import ReaCandidateVerifier, ReaProbePolicy


class FakeBackend:
    def __init__(self, version="6.9.0", tools=None, result=None):
        self.version = version
        self.tools = tools or [
            {"name": "get_capabilities", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "analyze", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
        ]
        self.result = result or {"content": [{"type": "text", "text": "REA ready"}]}
        self.closed = False

    async def discover(self):
        return {"server": {"name": "rea", "version": self.version}, "tools": self.tools}

    async def invoke(self, name, arguments):
        return self.result

    async def close(self):
        self.closed = True


class ReaVerificationTests(unittest.IsolatedAsyncioTestCase):
    def make_version(self, root, version="6.9.0"):
        version_root = root / "versions" / version
        package = version_root / "installation" / "node_modules" / "rea-agents"
        (package / "scripts").mkdir(parents=True)
        (package / "scripts" / "rea.mjs").write_text("// fixture", encoding="utf-8")
        (package / "package.json").write_text(json.dumps({"name": "rea-agents", "version": version}), encoding="utf-8")
        skill = package / "skills" / "reverse-engineer-anything" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: reverse-engineer-anything\n---\n", encoding="utf-8")
        return version_root

    async def test_real_catalog_identity_and_harmless_call_mark_candidate_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version_root = self.make_version(root)
            store = ReaProviderStore(root / "state.sqlite")
            candidate = store.discover("6.9.0", integrity="sha512-x", source="https://registry.npmjs.org")
            for state in ("acquiring", "staged"):
                candidate = store.transition("6.9.0", state, expected_revision=candidate.revision)
            backend = FakeBackend()
            verifier = ReaCandidateVerifier(
                root, store, lambda config: backend,
                ReaProbePolicy(required_tools=frozenset({"get_capabilities"}), harmless_tool="get_capabilities"),
                node_path="C:/Program Files/nodejs/node.exe",
            )

            evidence = await verifier.verify("6.9.0")

            self.assertEqual(store.candidate("6.9.0").state, "ready")
            self.assertEqual(evidence.server_version, "6.9.0")
            self.assertEqual(evidence.tool_count, 2)
            self.assertTrue(evidence.catalog_digest.startswith("sha256:"))
            self.assertTrue((version_root / "probe-evidence.json").is_file())
            self.assertTrue((version_root / "skill" / "SKILL.md").is_file())
            self.assertTrue(backend.closed)
            store.close()

    async def test_identity_or_catalog_mismatch_quarantines_without_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_version(root)
            store = ReaProviderStore(root / "state.sqlite")
            candidate = store.discover("6.9.0", integrity="sha512-x", source="https://registry.npmjs.org")
            for state in ("acquiring", "staged"):
                candidate = store.transition("6.9.0", state, expected_revision=candidate.revision)
            duplicate = [{"name": "get_capabilities", "inputSchema": {"type": "object"}}] * 2
            verifier = ReaCandidateVerifier(
                root, store, lambda config: FakeBackend(version="7.0.0", tools=duplicate),
                ReaProbePolicy(required_tools=frozenset({"get_capabilities"}), harmless_tool="get_capabilities"),
                node_path="node.exe",
            )

            with self.assertRaises(RuntimeError):
                await verifier.verify("6.9.0")

            self.assertEqual(store.candidate("6.9.0").state, "quarantined")
            self.assertIsNone(store.active())
            store.close()


if __name__ == "__main__":
    unittest.main()
