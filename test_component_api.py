import tempfile
import unittest
from pathlib import Path

from web_app.core.component_manager import ComponentManager
from web_app.core.component_registry import ComponentRequest, ComponentScope, ComponentSource


class ComponentManagerTests(unittest.TestCase):
    def test_plan_install_list_disable_are_real_and_global_by_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / "tool"
            tool.mkdir()
            (tool / "hello.cmd").write_text("@echo HELLO_COMPONENT\n", encoding="utf-8")
            manager = ComponentManager(root / "data")
            plan = manager.plan(ComponentRequest(source_kind=ComponentSource.local, source=str(tool)))
            self.assertEqual(ComponentScope.global_, plan.scope)
            result = manager.install(plan.plan_id)
            self.assertEqual("active", result["status"])
            self.assertEqual(1, len(manager.list("project-a")))
            manager.disable(plan.component_id, ComponentScope.global_)
            self.assertEqual(0, len(manager.list("project-a")))
            manager.close()


if __name__ == "__main__": unittest.main()
