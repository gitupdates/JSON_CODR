import tempfile
import unittest
from pathlib import Path

from web_app.core.component_probe import ComponentProbe
from web_app.core.component_registry import ComponentPlan, ComponentScope, ComponentSource
from web_app.core.component_runtime import ComponentRuntimeInstaller


class ComponentRuntimeTests(unittest.TestCase):
    def test_python_runtime_is_isolated_and_probe_records_real_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "pyproject.toml").write_text(
                "[project]\nname='fixture-tool'\nversion='1.0.0'\n[project.scripts]\nfixture-tool='fixture_tool:main'\n",
                encoding="utf-8",
            )
            (source / "fixture_tool.py").write_text(
                "def main():\n    print('FIXTURE_TOOL_OK')\n",
                encoding="utf-8",
            )
            plan = self._plan("python", ("fixture-tool",))
            runtime = ComponentRuntimeInstaller().install(plan, source, root / "runtimes")
            self.assertTrue(Path(runtime.interpreter).is_file())
            self.assertNotEqual(Path(runtime.interpreter).resolve(), Path(__import__('sys').executable).resolve())
            observation = ComponentProbe().probe(plan, runtime)
            self.assertTrue(observation.succeeded)
            self.assertIn("FIXTURE_TOOL_OK", observation.output)
            self.assertTrue(observation.evidence_digest.startswith("sha256:"))

    def test_failed_probe_reports_real_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "broken.cmd").write_text("@exit /b 9\n", encoding="utf-8")
            plan = self._plan("executable", ("broken",))
            runtime = ComponentRuntimeInstaller().install(plan, source, root / "runtimes")
            observation = ComponentProbe().probe(plan, runtime)
            self.assertFalse(observation.succeeded)
            self.assertEqual(9, observation.exit_code)

    @staticmethod
    def _plan(runtime_kind, entry_points):
        return ComponentPlan(
            plan_id="plan-fixture", component_id="component-fixture", source_kind=ComponentSource.local,
            source="fixture", scope=ComponentScope.global_, content_digest="sha256:" + "1" * 64,
            effects=("filesystem_write",), executable=True, entry_points=entry_points, runtime_kind=runtime_kind,
        )


if __name__ == "__main__":
    unittest.main()
