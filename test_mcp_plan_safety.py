import unittest

from web_app.core.adapters import CapabilityCall, ExecutionContext
from web_app.core.contracts import ConnectorStepMetadata, EffectClass, PlannedStep
from web_app.core.mcp_adapter import McpAdapter
from web_app.core.mcp_stdio_backend import McpServerConfig, normalize_mcp_catalog


class McpPlanSafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_catalog_has_stable_identities_and_schema_digests_without_config_secrets(self):
        config = McpServerConfig(
            name="issues", command="server", env={"TOKEN": "secret-value"},
            allowed_tools=frozenset({"find"}),
        )
        raw = {
            "server": {"name": "fixture", "version": "1"},
            "tools": [{
                "name": "find", "inputSchema": {"properties": {"q": {"type": "string"}}, "type": "object"},
                "annotations": {"readOnlyHint": True},
            }],
        }

        first = normalize_mcp_catalog(config, raw)
        reordered = normalize_mcp_catalog(config, {
            "tools": [{
                "annotations": {"readOnlyHint": True}, "name": "find",
                "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
            }],
            "server": {"version": "1", "name": "fixture"},
        })

        self.assertEqual(first, reordered)
        self.assertEqual(first["server_id"], "mcp.issues")
        self.assertEqual(first["tools"][0]["effect_class"], EffectClass.observe.value)
        self.assertNotIn("secret-value", str(first))
        self.assertNotIn("command", first)

    def test_schema_change_changes_reviewed_step_digest_and_unknown_annotation_is_external(self):
        config = McpServerConfig(name="issues", command="server")
        old = normalize_mcp_catalog(config, {"server": {}, "tools": [{
            "name": "create", "inputSchema": {"type": "object"}, "annotations": {"unknown": True},
        }]})["tools"][0]
        new = normalize_mcp_catalog(config, {"server": {}, "tools": [{
            "name": "create", "inputSchema": {"type": "object", "required": ["title"]},
            "annotations": {"unknown": True},
        }]})["tools"][0]
        self.assertEqual(old["effect_class"], EffectClass.external_effect.value)
        self.assertNotEqual(old["tool_schema_digest"], new["tool_schema_digest"])

        def planned(metadata):
            return PlannedStep(
                step_id="step-1", plan_id="plan-1", plan_revision=1,
                criterion_ids=("verified",), capability_id="mcp.issues", operation="unclassified",
                connector=ConnectorStepMetadata(
                    server_id="mcp.issues", tool_name="create",
                    tool_schema_digest=metadata["tool_schema_digest"],
                    argument_digest="sha256:" + "b" * 64,
                    declared_annotations=metadata["annotations"],
                ),
            )
        self.assertNotEqual(planned(old).canonical_digest, planned(new).canonical_digest)

    async def test_interrupted_call_is_not_automatically_replayed(self):
        class Backend:
            calls = 0

            async def invoke(self, name, arguments):
                self.calls += 1
                raise InterruptedError("interrupted")

        backend = Backend()
        adapter = McpAdapter(backend, allowed_tools=frozenset({"create"}), server_id="mcp.issues")
        call = CapabilityCall(
            capability_id="mcp.issues", operation="invoke", project_root="C:/project",
            arguments={"tool": "create", "arguments": {"title": "one"}},
        )
        context = ExecutionContext(task_id="task-1", project_id="project-1", principal="user")

        with self.assertRaises(InterruptedError):
            async for _ in adapter.execute(call, context):
                pass
        self.assertEqual(backend.calls, 1)


if __name__ == "__main__":
    unittest.main()
