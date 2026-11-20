import unittest
from pathlib import Path


class ComponentWebTests(unittest.TestCase):
    def test_install_component_surface_and_client_are_shipped(self):
        root = Path(__file__).parent
        html = (root / "web/index.html").read_text(encoding="utf-8")
        client = (root / "web/core_client.js").read_text(encoding="utf-8")
        script = (root / "web/app.js").read_text(encoding="utf-8")
        self.assertIn('id="component-source"', html)
        self.assertIn('id="component-plan"', html)
        self.assertIn('<option value="python">PyPI package</option>', html)
        self.assertIn('<option value="node">npm package</option>', html)
        self.assertIn("planComponent", client)
        self.assertIn("installComponent", client)
        self.assertIn("loadComponents", script)
        self.assertIn("normalization: pendingComponentPlan.normalization", script)


if __name__ == "__main__": unittest.main()
