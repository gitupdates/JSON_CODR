import tempfile
import unittest
from pathlib import Path

from web_app.core.capability_discovery import discover_project_profile


class CapabilityDiscoveryTests(unittest.TestCase):
    def test_manifest_only_discovery_covers_coding_and_infrastructure_stacks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("pyproject.toml", "package.json", "demo.csproj", "pom.xml", "go.mod", "Cargo.toml",
                         "Dockerfile", "playwright.config.ts", "schema.sql", "main.tf", "main.bicep",
                         "template.yaml", "deployment.yaml", "Chart.yaml"):
                (root / name).write_text("untrusted", encoding="utf-8")
            profile = discover_project_profile(root)
        self.assertTrue({"python", "node", "dotnet", "java", "go", "rust", "containers",
                         "browser", "database", "terraform", "bicep", "cloudformation",
                         "kubernetes", "helm"}.issubset(profile.kinds))
        self.assertEqual(profile.trust, "untrusted_manifest_evidence")


if __name__ == "__main__":
    unittest.main()
