import unittest

from web_app.core.capability_catalog import CapabilityCatalog, CapabilityDefinition, lifecycle_definitions


class CapabilityCatalogTests(unittest.TestCase):
    def definition(self, capability_id="project.read"):
        return CapabilityDefinition(
            capability_id=capability_id, version="1", description="Read project text",
            input_schema={"type": "object", "additionalProperties": False},
            effect_class="read", approval_class="automatic", adapter_id=capability_id,
            adapter_digest="sha256:" + "1" * 64, rollback_class="none",
        )

    def test_ids_are_unique_and_definition_digest_is_stable(self):
        catalog = CapabilityCatalog((self.definition(),), probed_adapters={"project.read"})
        self.assertEqual(catalog.definitions[0].definition_digest, catalog.definitions[0].definition_digest)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            CapabilityCatalog((self.definition(), self.definition()), probed_adapters={"project.read"})

    def test_unprobed_and_missing_prerequisites_are_explained_and_excluded_from_schema(self):
        definition = self.definition("test.run").model_copy(update={"prerequisites": ("python",)})
        catalog = CapabilityCatalog((definition,), probed_adapters=set())
        availability = catalog.list_for_project({"python"})[0]
        self.assertFalse(availability.available)
        self.assertIn("adapter was not probed", availability.reasons)
        self.assertEqual(catalog.planner_schema({"python"})["properties"]["capability_id"]["enum"], [])

    def test_full_lifecycle_includes_coding_tooling_and_guarded_delivery(self):
        definitions = {item.capability_id: item for item in lifecycle_definitions()}
        required = {
            "project.read", "project.patch", "code.refactor", "code.debug", "code.document",
            "code.review", "build.run", "test.run", "lint.run", "format.run", "typecheck.run",
            "package.build", "benchmark.run", "application.run", "dependency.audit",
            "dependency.update", "license.audit", "vulnerability.scan", "git.execute",
            "service.manage", "database.manage", "container.manage", "browser.test", "api.test",
            "desktop.test", "mcp.manage", "lsp.inspect", "debugger.run", "profiler.run",
            "infrastructure.preview", "infrastructure.apply", "deployment.preview",
            "deployment.apply", "deployment.health", "deployment.logs", "deployment.rollback",
        }
        self.assertTrue(required.issubset(definitions))
        self.assertEqual(definitions["deployment.apply"].approval_class, "strong_exact")
        self.assertEqual(definitions["infrastructure.apply"].effect_class, "infrastructure")


if __name__ == "__main__":
    unittest.main()
