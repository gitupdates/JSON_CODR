import tempfile
import unittest
from pathlib import Path

from web_app.core.component_manager import ComponentManager
from web_app.core.component_registry import ComponentRequest, ComponentScope, ComponentSource


class ComponentManagerTests(unittest.TestCase):
    def test_installed_runtime_catalog_contains_only_persisted_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); tool = root / "tool"; tool.mkdir()
            (tool / "hello.cmd").write_text("@echo HELLO\n")
            manager = ComponentManager(root / "data")
            try:
                plan = manager.plan(ComponentRequest(source_kind=ComponentSource.local, source=str(tool)))
                manager.install(plan.plan_id, plan.approval_digest)
                command = manager.catalog.resolve_components("project-a")[0].commands["hello"][0]
                self.assertTrue(Path(command).is_file())
                self.assertNotIn(".staging", command)
            finally:
                manager.close()

    def test_plan_install_list_disable_are_real_and_global_by_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / "tool"
            tool.mkdir()
            (tool / "hello.cmd").write_text("@echo HELLO_COMPONENT\n", encoding="utf-8")
            manager = ComponentManager(root / "data")
            try:
                plan = manager.plan(ComponentRequest(source_kind=ComponentSource.local, source=str(tool)))
                self.assertEqual(ComponentScope.global_, plan.scope)
                self.assertNotEqual(plan.content_digest, plan.approval_digest)
                with self.assertRaises(PermissionError):
                    manager.install(plan.plan_id, plan.content_digest)
                result = manager.install(plan.plan_id, plan.approval_digest)
                self.assertEqual("active", result["status"])
                self.assertEqual("native", result["normalization"]["decision"]["mode"])
                self.assertTrue(result["normalization"]["verification"]["succeeded"])
                self.assertEqual(0, result["normalization"]["verification"]["exit_code"])
                self.assertEqual(1, len(manager.list("project-a")))
                manager.disable(plan.component_id, ComponentScope.global_)
                self.assertEqual(0, len(manager.list("project-a")))
            finally:
                manager.close()

    def test_plan_survives_restart_and_requires_matching_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); tool = root / "tool"; tool.mkdir()
            (tool / "hello.cmd").write_text("@echo HELLO\n")
            manager = ComponentManager(root / "data")
            plan = manager.plan(ComponentRequest(source_kind=ComponentSource.local, source=str(tool)))
            manager.close()
            manager = ComponentManager(root / "data")
            try:
                with self.assertRaises(PermissionError): manager.install(plan.plan_id, "sha256:" + "0" * 64)
                self.assertEqual("active", manager.install(plan.plan_id, plan.approval_digest)["status"])
            finally:
                manager.close()


if __name__ == "__main__": unittest.main()
