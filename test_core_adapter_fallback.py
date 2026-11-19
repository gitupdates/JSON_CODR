import unittest
import tempfile
from pathlib import Path

from web_app.core.adapters import CapabilityCall, ExecutionContext
from web_app.core.mcp_adapter import McpAdapter
from web_app.core.policy import PolicyEffect, PolicyService
from web_app.core.contracts import TaskEventDraft


class AdapterFallbackTests(unittest.TestCase):
    def test_prefers_verified_native_capability(self):
        from web_app.core.adapter_fallback import AdapterFallbackRouter

        call = CapabilityCall(
            capability_id="native.read",
            operation="read",
            project_root=".",
            target_path="README.md",
        )
        route = AdapterFallbackRouter.resolve(call, {"native.read"}, {"native.read", "mcp.rea"})

        self.assertEqual(route.kind, "native")
        self.assertEqual(route.capability_id, "native.read")

    def test_routes_explicit_bridge_capability_to_compatibility_adapter(self):
        from web_app.core.adapter_fallback import AdapterFallbackRouter

        call = CapabilityCall(
            capability_id="mcp.rea",
            operation="invoke",
            project_root=".",
            arguments={"tool": "open_binary", "arguments": {}},
        )
        route = AdapterFallbackRouter.resolve(call, {"native.read"}, {"mcp.rea"})

        self.assertEqual(route.kind, "compatibility")
        self.assertEqual(route.capability_id, "mcp.rea")

    def test_does_not_claim_an_unavailable_capability(self):
        from web_app.core.adapter_fallback import AdapterFallbackRouter

        call = CapabilityCall(capability_id="mcp.missing", operation="invoke", project_root=".")
        route = AdapterFallbackRouter.resolve(call, {"native.read"}, {"mcp.rea"})

        self.assertEqual(route.kind, "unavailable")
        self.assertIsNone(route.capability_id)

    def test_read_only_mcp_discovery_is_automatically_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = PolicyService(Path(directory) / "policy.sqlite")
            try:
                decision = policy.evaluate("user", "project-1", CapabilityCall(
                    capability_id="mcp.rea", operation="discover", project_root=directory,
                ))
            finally:
                policy.close()
        self.assertEqual(decision.effect, PolicyEffect.allow)


class McpApprovalEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rea_discovery_and_invocation_report_real_approval(self):
        class Backend:
            async def discover(self):
                return {"tools": [{"name": "inspect"}]}

            async def invoke(self, tool, arguments):
                return {"tool": tool, "arguments": arguments}

        adapter = McpAdapter(Backend(), allowed_tools={"*"})
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")
        discovery = [event async for event in adapter.execute(CapabilityCall(
            capability_id="mcp.rea", operation="discover", project_root=".",
        ), context)]
        invoked = [event async for event in adapter.execute(CapabilityCall(
            capability_id="mcp.rea", operation="invoke", project_root=".",
            arguments={"tool": "inspect", "arguments": {"path": "README.md"}},
        ), context)]

        self.assertEqual(discovery[0].event_type, "mcp.discover.completed")
        self.assertEqual(discovery[0].payload["approval_state"], "not_required")
        self.assertEqual(invoked[0].payload["approval_state"], "approved")
        self.assertEqual(invoked[0].payload["execution_route"], "compatibility")
        self.assertEqual(invoked[0].payload["adapter_id"], "mcp.rea")

    async def test_large_discovery_is_bounded_for_durable_task_events(self):
        class Backend:
            async def discover(self):
                return {"server": {"name": "rea"}, "tools": [
                    {"name": f"tool-{index}", "description": "x" * 10000, "inputSchema": {"type": "object"}}
                    for index in range(200)
                ]}

        adapter = McpAdapter(Backend(), allowed_tools={"*"})
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")
        events = [event async for event in adapter.execute(CapabilityCall(
            capability_id="mcp.rea", operation="discover", project_root=".",
        ), context)]

        durable = TaskEventDraft(event_type=events[0].event_type, payload=events[0].payload)
        self.assertEqual(durable.payload["tool_count"], 200)
        self.assertTrue(durable.payload["catalog_truncated"])
        self.assertLessEqual(len(durable.payload["tools"]), 100)


if __name__ == "__main__":
    unittest.main()
