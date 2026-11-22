import unittest

from web_app.designer.components import ComponentRegistry
from web_app.designer.continuity import REQUIRED_CORE_CAPABILITIES, validate_runtime_continuity
from web_app.designer.contracts import DesignDocument, DesignNode
from web_app.designer.json_codr_manifest import FIXED_RUNTIME_CAPABILITIES, create_json_codr_overlay


class DesignerContinuityTests(unittest.TestCase):
    @staticmethod
    def rebuild(document: DesignDocument, **changes) -> DesignDocument:
        payload = document.model_dump(mode="json", exclude={"canonical_digest"})
        payload.update(changes)
        return DesignDocument.model_validate(payload)

    def test_core_function_may_move_or_change_visuals_but_remains_reachable(self):
        document = create_json_codr_overlay()
        payload = document.model_dump(mode="json", exclude={"canonical_digest"})
        shell = next(node for node in payload["nodes"] if node["node_id"] == "application-shell")
        shell["children"] = list(reversed(shell["children"]))
        navigation = next(node for node in payload["nodes"] if node["node_id"] == "primary-navigation")
        navigation["properties"]["label"] = "Projects"
        changed = DesignDocument.model_validate(payload)

        violations = validate_runtime_continuity(changed, ComponentRegistry.builtins())

        self.assertEqual(violations, ())

    def test_deleting_last_route_to_core_function_blocks_publication(self):
        document = create_json_codr_overlay()
        payload = document.model_dump(mode="json", exclude={"canonical_digest"})
        payload["nodes"] = [node for node in payload["nodes"] if node["node_id"] != "primary-navigation"]
        shell = next(node for node in payload["nodes"] if node["node_id"] == "application-shell")
        shell["children"] = [node_id for node_id in shell["children"] if node_id != "primary-navigation"]
        changed = DesignDocument.model_validate(payload)

        violations = validate_runtime_continuity(changed, ComponentRegistry.builtins())

        self.assertIn("workspace.navigation", {violation.capability for violation in violations})

    def test_unknown_component_requires_fallback_and_migration(self):
        document = create_json_codr_overlay()
        payload = document.model_dump(mode="json", exclude={"canonical_digest"})
        payload["nodes"].append(
            DesignNode(
                node_id="custom-widget",
                component_type="vendor.widget",
                parent_id="application-shell",
            ).model_dump(mode="json")
        )
        shell = next(node for node in payload["nodes"] if node["node_id"] == "application-shell")
        shell["children"].append("custom-widget")
        changed = DesignDocument.model_validate(payload)

        violations = validate_runtime_continuity(changed, ComponentRegistry.builtins())

        self.assertIn("component_unavailable", {violation.code for violation in violations})

    def test_recovery_shell_is_not_an_editable_node(self):
        document = create_json_codr_overlay()
        editable_capabilities = {
            node.properties.get("core_capability")
            for node in document.nodes
            if node.properties.get("core_capability")
        }

        self.assertIn("recovery.open", FIXED_RUNTIME_CAPABILITIES)
        self.assertIn("safe_mode.open", FIXED_RUNTIME_CAPABILITIES)
        self.assertNotIn("recovery.open", editable_capabilities)
        self.assertNotIn("safe_mode.open", editable_capabilities)
        self.assertTrue(REQUIRED_CORE_CAPABILITIES.issuperset(FIXED_RUNTIME_CAPABILITIES))


if __name__ == "__main__":
    unittest.main()
