import unittest

from web_app.designer.components import BUILTIN_COMPONENT_TYPES, ComponentRegistry
from web_app.designer.json_codr_manifest import (
    JSON_CODR_MANIFEST_VERSION,
    PROTECTED_REGION_IDS,
    create_json_codr_overlay,
)
from web_app.designer.templates import TEMPLATE_IDS, create_template


EXPECTED_COMPONENTS = {
    "container", "stack", "grid", "text", "heading", "button", "link", "input",
    "textarea", "select", "checkbox", "image", "icon", "navigation", "tabs", "card",
    "table", "list", "form", "dialog", "divider", "spacer", "component_instance",
}

EXPECTED_REGIONS = {
    "application-shell", "primary-navigation", "top-bar", "workspace", "context-files-panel",
    "skills-panel", "hardware-panel", "settings-panel", "composer", "response-cards",
    "plan-review-panels", "status-indicators", "terminal-container", "designer-exit",
    "recovery-controls", "approval-controls",
}


class ComponentRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ComponentRegistry.builtins()

    def test_catalog_is_complete_and_definitions_are_data_only(self):
        self.assertEqual(set(BUILTIN_COMPONENT_TYPES), EXPECTED_COMPONENTS)
        self.assertEqual(set(self.registry.types()), EXPECTED_COMPONENTS)
        for component_type in EXPECTED_COMPONENTS:
            with self.subTest(component_type=component_type):
                definition = self.registry.get(component_type)
                self.assertEqual(definition.component_type, component_type)
                self.assertFalse(definition.inert_placeholder)
                self.assertIsInstance(definition.property_schema, dict)
                self.assertTrue(definition.semantic_exporter)
                self.assertFalse(any(callable(value) for value in definition.model_dump().values()))

    def test_structural_rules_actions_and_accessibility_are_explicit(self):
        self.assertIn("text", self.registry.get("container").allowed_children)
        self.assertEqual(self.registry.get("text").allowed_children, ())
        self.assertIn("activate", self.registry.get("button").action_slots)
        self.assertIn("label", self.registry.get("input").accessibility_requirements)
        self.assertIn("alt", self.registry.get("image").accessibility_requirements)
        self.assertEqual(self.registry.get("heading").semantic_exporter, "heading")
        self.assertIn("level", self.registry.get("heading").property_schema)

    def test_unknown_definition_is_preserved_as_an_inert_placeholder(self):
        unknown = self.registry.resolve("future-chart")
        self.assertEqual(unknown.component_type, "future-chart")
        self.assertTrue(unknown.inert_placeholder)
        self.assertEqual(unknown.allowed_children, ())
        self.assertEqual(unknown.action_slots, ())
        with self.assertRaises(KeyError):
            self.registry.get("future-chart")

    def test_registry_rejects_duplicate_definitions(self):
        definition = self.registry.get("text")
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.registry.register(definition)


class TemplateTests(unittest.TestCase):
    def test_all_portable_templates_create_valid_independent_documents(self):
        self.assertEqual(set(TEMPLATE_IDS), {"blank", "landing-page", "dashboard", "form"})
        for template_id in TEMPLATE_IDS:
            with self.subTest(template_id=template_id):
                first = create_template(template_id, f"{template_id} one")
                second = create_template(template_id, f"{template_id} two")
                self.assertNotEqual(first.project_id, second.project_id)
                self.assertEqual(first.metadata["template_id"], template_id)
                self.assertEqual(first.metadata["theme"], "noc-light")
                self.assertEqual(first.tokens["font_family"], "system-ui")
                self.assertTrue(set(node.component_type for node in first.nodes) <= EXPECTED_COMPONENTS)
                self.assertTrue(first.canonical_digest.startswith("sha256:"))

    def test_templates_exercise_expected_semantics_without_remote_assets(self):
        landing = create_template("landing-page", "Landing")
        dashboard = create_template("dashboard", "Dashboard")
        form = create_template("form", "Form")
        self.assertTrue({"heading", "text", "button"} <= {node.component_type for node in landing.nodes})
        self.assertTrue({"navigation", "grid", "card", "table"} <= {node.component_type for node in dashboard.nodes})
        self.assertTrue({"form", "input", "textarea", "select", "checkbox", "button"} <= {node.component_type for node in form.nodes})
        for document in (landing, dashboard, form):
            self.assertNotIn("http://", document.model_dump_json())
            self.assertNotIn("https://", document.model_dump_json())

    def test_unknown_template_is_rejected(self):
        with self.assertRaises(KeyError):
            create_template("unknown", "Nope")


class ProtectedManifestTests(unittest.TestCase):
    def test_manifest_has_versioned_complete_region_coverage(self):
        self.assertGreaterEqual(JSON_CODR_MANIFEST_VERSION, 1)
        self.assertEqual(set(PROTECTED_REGION_IDS), EXPECTED_REGIONS)
        overlay = create_json_codr_overlay({"preset": "noc-light", "density": "compact"})
        self.assertEqual(overlay.mode, "json_codr")
        self.assertEqual({node.node_id for node in overlay.nodes}, EXPECTED_REGIONS)
        self.assertEqual(overlay.metadata["manifest_version"], JSON_CODR_MANIFEST_VERSION)

    def test_essential_regions_are_fully_protected_and_appearance_is_data_only(self):
        overlay = create_json_codr_overlay({"preset": "noc-light", "typography": "system"})
        by_id = {node.node_id: node for node in overlay.nodes}
        essential = {
            "application-shell", "primary-navigation", "settings-panel", "designer-exit",
            "recovery-controls", "approval-controls",
        }
        for node_id in essential:
            self.assertEqual(
                set(by_id[node_id].locked_capabilities),
                {"delete", "rebind", "move_outside_region", "hide", "rename"},
            )
        self.assertIn("rebind", by_id["terminal-container"].locked_capabilities)
        serialized = overlay.model_dump_json()
        self.assertNotIn("onclick", serialized.lower())
        self.assertNotIn("function", serialized.lower())


if __name__ == "__main__":
    unittest.main()
