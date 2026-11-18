import json
import tempfile
import unittest
from pathlib import Path

from web_app.core.component_catalog import ComponentCatalog, active_component_command
from web_app.core.component_registry import ComponentRegistry, ComponentRequest, ComponentScope, ComponentSource
from web_app.core.component_shims import ShimManager


class ComponentCatalogTests(unittest.TestCase):
    def test_project_override_and_private_component_do_not_leak(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = ComponentRegistry(Path(temporary) / "registry.sqlite")
            global_id = self._activate(registry, temporary, "global-tool", ComponentScope.global_)
            private_id = self._activate(registry, temporary, "private-tool", ComponentScope.project, "project-a")
            catalog = ComponentCatalog(registry)
            self.assertEqual({global_id, private_id}, {item.component_id for item in catalog.resolve_components("project-a")})
            self.assertEqual({global_id}, {item.component_id for item in catalog.resolve_components("project-b")})
            registry.close()

    def test_shims_keep_namespaced_commands_and_omit_ambiguous_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = ShimManager(Path(temporary))
            manager.refresh({"one": {"shared": ("cmd", "/c", "exit", "0")}, "two": {"shared": ("cmd", "/c", "exit", "0")}})
            self.assertTrue((Path(temporary) / "borg-one-shared.cmd").is_file())
            self.assertTrue((Path(temporary) / "borg-two-shared.cmd").is_file())
            self.assertFalse((Path(temporary) / "shared.cmd").exists())

    def test_active_component_command_reads_and_closes_global_registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = ComponentRegistry(root / "registry.sqlite")
            self._activate(registry, temporary, "craft-anything-cli", ComponentScope.global_)
            registry.close()

            command = active_component_command(root, "craft-anything-cli")

            self.assertEqual(command, ("cmd", "/c", "exit", "0"))
            (root / "registry.sqlite").unlink()

    @staticmethod
    def _activate(registry, temporary, name, scope, project_id=None):
        plan = registry.plan(ComponentRequest(source_kind=ComponentSource.local, source=str(Path(temporary) / name), scope=scope, project_id=project_id), executable=True, entry_points=(name,), runtime_kind="executable")
        runtime = Path(temporary) / "runtime" / name
        runtime.mkdir(parents=True)
        (runtime / "runtime.json").write_text(json.dumps({name: ["cmd", "/c", "exit", "0"]}))
        generation = registry.stage(plan, runtime_root=str(runtime))
        registry.record_probe(plan.component_id, generation.generation, succeeded=True, evidence_digest="sha256:" + "2" * 64)
        registry.activate(plan.component_id, generation.generation, scope=scope, project_id=project_id)
        return plan.component_id


if __name__ == "__main__": unittest.main()
