import tempfile
import unittest
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from web_app.core.component_probe import ComponentProbe
from web_app.core.component_registry import ComponentPlan, ComponentScope, ComponentSource
from web_app.core.component_runtime import ComponentRuntimeInstaller


class ComponentRuntimeTests(unittest.TestCase):
    def test_runtime_rejects_source_changed_after_plan_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"; source.mkdir()
            (source / "tool.cmd").write_text("@exit /b 0\n")
            plan = self._plan("executable", ("tool",)).model_copy(update={"content_digest": "sha256:" + "0" * 64})
            with self.assertRaisesRegex(ValueError, "approved content digest"):
                ComponentRuntimeInstaller().install(plan, source, root / "runtimes")

    def test_python_coordinate_installs_offline_with_all_artifact_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"; artifacts = source / "artifacts"; artifacts.mkdir(parents=True)
            wheel = artifacts / "sample_tool-1.2.3-py3-none-any.whl"; wheel.write_bytes(b"wheel")
            import hashlib
            sha = hashlib.sha256(b"wheel").hexdigest()
            (source / "component-resolution.json").write_text(json.dumps({
                "format": 1, "ecosystem": "python", "coordinate": "sample-tool==1.2.3",
                "artifacts": [{"filename": wheel.name, "sha256": sha, "name": "sample-tool", "version": "1.2.3", "entry_points": {"sample-tool": "sample_tool:main"}}],
                "entry_points": {"sample-tool": "sample_tool:main"},
            }))
            (source / "component-normalization.json").write_text(json.dumps({
                "format": 1, "ecosystem": "python", "coordinate": "sample-tool==1.2.3",
                "decision": {"mode": "adapted", "reason": "portable launcher required"},
                "extracted": {"entry_points": {"sample-tool": "sample_tool:main"}},
                "alterations": [{"id": "python-metadata-launcher", "required": True}],
            }))
            from web_app.core.component_acquisition import _tree_digest
            plan = self._plan("python", ("sample-tool",)).model_copy(update={
                "content_digest": _tree_digest(source), "source_kind": ComponentSource.python,
            })

            def fake_venv(path):
                scripts = Path(path) / "Scripts"; scripts.mkdir(parents=True)
                (scripts / "python.exe").write_bytes(b"")
                (scripts / "sample-tool.exe").write_bytes(b"")
            with patch("web_app.core.component_runtime.venv.EnvBuilder.create", side_effect=fake_venv), patch(
                "web_app.core.component_runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")
            ) as run:
                runtime = ComponentRuntimeInstaller().install(plan, source, root / "runtimes")
            command = run.call_args.args[0]
            self.assertIn("--no-index", command)
            self.assertIn("--require-hashes", command)
            self.assertIn("--only-binary=:all:", command)
            self.assertEqual(runtime.entry_points["sample-tool"][0], runtime.interpreter)
            self.assertIn("importlib.metadata", runtime.entry_points["sample-tool"][2])
            self.assertIn("sys.exit", runtime.entry_points["sample-tool"][2])
            report = json.loads((Path(runtime.runtime_root) / "normalization.json").read_text())
            native = report["installation"]["native_commands"]["sample-tool"]
            self.assertTrue(native[0].endswith("sample-tool.exe"))
            self.assertTrue(Path(native[0]).is_file())
            self.assertEqual(report["installation"]["declared_command_names"], ["sample-tool"])
            self.assertEqual(report["installation"]["effective_commands"]["sample-tool"], list(runtime.entry_points["sample-tool"]))
            self.assertNotIn(".staging", json.dumps(report["installation"]))

    def test_node_coordinate_runtime_reuses_approved_tree_without_network_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / "source"; package = source / "node_modules" / "sample-tool"
            package.mkdir(parents=True)
            (source / "package.json").write_text(json.dumps({"dependencies": {"sample-tool": "1.2.3"}}))
            (source / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3}))
            (package / "cli.js").write_text("console.log('ok')")
            (source / "component-resolution.json").write_text(json.dumps({
                "format": 1, "ecosystem": "node", "coordinate": "sample-tool@1.2.3",
                "entry_points": {"sample-tool": "node_modules/sample-tool/cli.js"},
            }))
            from web_app.core.component_acquisition import _tree_digest
            plan = self._plan("node", ("sample-tool",)).model_copy(update={
                "content_digest": _tree_digest(source), "source_kind": ComponentSource.node,
            })
            with patch("web_app.core.component_runtime.subprocess.run") as run, patch(
                "web_app.core.component_runtime.shutil.which", return_value=r"C:\Program Files\nodejs\node.exe"
            ):
                runtime = ComponentRuntimeInstaller().install(plan, source, root / "runtimes")
            run.assert_not_called()
            self.assertEqual(runtime.entry_points["sample-tool"][0], r"C:\Program Files\nodejs\node.exe")
            self.assertTrue(Path(runtime.entry_points["sample-tool"][1]).is_file())

    def test_node_bin_target_cannot_escape_approved_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / "source"; source.mkdir()
            (root / "outside.js").write_text("console.log('escape')")
            (source / "package.json").write_text(json.dumps({
                "name": "bad", "version": "1.0.0", "bin": {"bad": "../outside.js"},
            }))
            from web_app.core.component_acquisition import _tree_digest
            plan = self._plan("node", ("bad",)).model_copy(update={"content_digest": _tree_digest(source)})
            with self.assertRaisesRegex(ValueError, "escapes"):
                ComponentRuntimeInstaller().install(plan, source, root / "runtimes")

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
            from web_app.core.component_acquisition import _tree_digest
            plan = self._plan("python", ("fixture-tool",)).model_copy(update={"content_digest": _tree_digest(source)})
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
            from web_app.core.component_acquisition import _tree_digest
            plan = self._plan("executable", ("broken",)).model_copy(update={"content_digest": _tree_digest(source)})
            runtime = ComponentRuntimeInstaller().install(plan, source, root / "runtimes")
            observation = ComponentProbe().probe(plan, runtime)
            self.assertFalse(observation.succeeded)
            self.assertEqual(9, observation.exit_code)

    def test_probe_uses_help_and_requires_every_exported_command_to_pass(self):
        plan = self._plan("node", ("one", "two"))
        from web_app.core.component_runtime import InstalledRuntime
        runtime = InstalledRuntime(
            component_id=plan.component_id, runtime_root="fixture", runtime_kind="node",
            entry_points={"one": ("one",), "two": ("two",)},
        )
        outcomes = [subprocess.CompletedProcess([], 0, "one help", ""), subprocess.CompletedProcess([], 9, "", "two failed")]
        with patch("web_app.core.component_probe.subprocess.run", side_effect=outcomes) as run:
            observation = ComponentProbe().probe(plan, runtime)
        self.assertFalse(observation.succeeded)
        self.assertEqual(run.call_args_list[0].args[0], ("one", "--help"))
        self.assertEqual(run.call_args_list[1].args[0], ("two", "--help"))
        self.assertIn("two failed", observation.output)
        self.assertEqual(run.call_args_list[0].kwargs["cwd"], "fixture")
        self.assertNotIn("GITHUB_TOKEN", run.call_args_list[0].kwargs["env"])

    def test_probe_launch_error_becomes_failed_evidence(self):
        plan = self._plan("executable", ("missing",))
        from web_app.core.component_runtime import InstalledRuntime
        runtime = InstalledRuntime(
            component_id=plan.component_id, runtime_root="fixture", runtime_kind="executable",
            entry_points={"missing": ("missing",)},
        )
        with patch("web_app.core.component_probe.subprocess.run", side_effect=FileNotFoundError("missing executable")):
            observation = ComponentProbe().probe(plan, runtime)
        self.assertFalse(observation.succeeded)
        self.assertEqual(127, observation.exit_code)
        self.assertIn("missing executable", observation.output)

    @staticmethod
    def _plan(runtime_kind, entry_points):
        return ComponentPlan(
            plan_id="plan-fixture", component_id="component-fixture", source_kind=ComponentSource.local,
            source="fixture", scope=ComponentScope.global_, content_digest="sha256:" + "1" * 64,
            approval_digest="sha256:" + "2" * 64,
            effects=("filesystem_write",), executable=True, entry_points=entry_points, runtime_kind=runtime_kind,
        )


if __name__ == "__main__":
    unittest.main()
