import tempfile
import unittest
from pathlib import Path

from web_app.core.adapters import CapabilityCall, ExecutionContext
from web_app.core.analysis_adapter import AnalysisAdapter
from web_app.core.assimilation import AssimilationService
from web_app.core.browser_adapter import BrowserAdapter
from web_app.core.language_adapter import LanguageAdapter
from web_app.core.mcp_adapter import McpAdapter


async def collect(adapter, call):
    context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")
    return [event async for event in adapter.execute(call, context)]


class ExtendedCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_language_browser_mcp_and_analysis_adapters_return_real_evidence(self):
        class LanguageBackend:
            async def symbols(self, path):
                raise RuntimeError("LSP unavailable")

            async def parse(self, path):
                return {"symbols": ["main"], "engine": "tree-sitter"}

        class BrowserBackend:
            async def inspect(self, url):
                return {"url": url, "dom": "<main>ready</main>", "screenshot": "artifact:shot-1"}

        class McpBackend:
            async def discover(self):
                return {"tools": [{"name": "search", "inputSchema": {"type": "object"}}]}

            async def invoke(self, name, arguments):
                return {"name": name, "result": arguments["query"]}

        class AnalysisBackend:
            async def available(self, tool):
                return tool == "rea"

            async def run(self, tool, target):
                return {"tool": tool, "target": target, "evidence": "artifact:analysis-1"}

        root = str(Path.cwd())
        language = await collect(LanguageAdapter(LanguageBackend()), CapabilityCall(
            capability_id="code.symbols", operation="read", project_root=root, arguments={"path": "app.py"}
        ))
        browser = await collect(BrowserAdapter(BrowserBackend()), CapabilityCall(
            capability_id="browser.inspect", operation="read", project_root=root, arguments={"url": "http://localhost"}
        ))
        mcp = await collect(McpAdapter(McpBackend(), allowed_tools={"search"}), CapabilityCall(
            capability_id="mcp.invoke", operation="read", project_root=root,
            arguments={"tool": "search", "arguments": {"query": "needle"}},
        ))
        analysis = await collect(AnalysisAdapter(AnalysisBackend()), CapabilityCall(
            capability_id="ghidra.analyze", operation="read", project_root=root, arguments={"target": "sample.exe"}
        ))

        self.assertEqual(language[0].payload["engine"], "tree-sitter")
        self.assertEqual(browser[0].payload["screenshot"], "artifact:shot-1")
        self.assertEqual(mcp[0].payload["result"], "needle")
        self.assertFalse(analysis[0].payload["available"])
        self.assertEqual(analysis[0].payload["reason"], "ghidra is unavailable")

    async def test_assimilation_quarantines_deduplicates_probes_and_scopes_enablement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "SKILL.md"
            source.write_text("# Review skill", encoding="utf-8")
            probes = []

            async def probe(manifest, staged):
                probes.append(manifest.component_id)
                return {"success": True, "evidence": "artifact:probe-1"}

            service = AssimilationService(root / "components", probe)
            identified = service.identify(source)
            first = await service.install(identified)
            duplicate = await service.install(identified)

            self.assertEqual(identified.kind, "skill")
            self.assertEqual(first.component_id, duplicate.component_id)
            self.assertEqual(probes, [first.component_id])
            self.assertEqual(service.status(first.component_id).state, "verified")
            enabled = service.enable(first.component_id, project_id="project-1")
            self.assertEqual(enabled.project_ids, ("project-1",))
            promoted = service.promote(first.component_id)
            self.assertTrue(promoted.global_enabled)
            self.assertEqual(service.provenance(first.component_id).source, str(source.resolve()))
            service.remove(first.component_id)
            with self.assertRaises(KeyError):
                service.status(first.component_id)


if __name__ == "__main__":
    unittest.main()
