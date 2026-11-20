import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from web_app.core.component_acquisition import AcquiredComponent, ComponentAcquirer, parse_package_coordinate, _enforce_tree_limits
from web_app.core.component_inspection import ComponentInspector
from web_app.core.component_registry import ComponentRegistry, ComponentRequest, ComponentScope, ComponentSource


class ComponentAcquisitionTests(unittest.TestCase):
    def test_package_staging_limits_reject_dependency_bombs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one").write_bytes(b"1")
            (root / "two").write_bytes(b"2")
            with self.assertRaisesRegex(ValueError, "file-count limit"):
                _enforce_tree_limits(root, max_files=1, max_bytes=100)

    def test_exact_public_package_coordinates_are_normalized(self):
        self.assertEqual(parse_package_coordinate(ComponentSource.python, "Packaging==24.2"), ("packaging", "24.2"))
        self.assertEqual(parse_package_coordinate(ComponentSource.node, "@Scope/Tool@1.2.3"), ("@scope/tool", "1.2.3"))

    def test_ambiguous_or_executable_package_coordinates_are_rejected(self):
        rejected = (
            (ComponentSource.python, "packaging>=24"),
            (ComponentSource.python, "packaging==24.2; python_version>'3'"),
            (ComponentSource.python, "https://example.test/tool.whl"),
            (ComponentSource.node, "tool@latest"),
            (ComponentSource.node, "tool@^1.2.3"),
            (ComponentSource.node, "alias@npm:tool@1.2.3"),
        )
        for kind, coordinate in rejected:
            with self.subTest(coordinate=coordinate), self.assertRaisesRegex(ValueError, "exact"):
                parse_package_coordinate(kind, coordinate)

    def test_python_coordinate_downloads_only_wheels_and_records_hashes(self):
        def fake_run(command, **kwargs):
            destination = Path(command[command.index("--dest") + 1])
            wheel = destination / "sample_tool-1.2.3-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("sample_tool-1.2.3.dist-info/METADATA", "Name: sample-tool\nVersion: 1.2.3\n")
                archive.writestr("sample_tool-1.2.3.dist-info/entry_points.txt", "[console_scripts]\nsample-tool = sample_tool:main\n")
            return subprocess.CompletedProcess(command, 0, "", "")

        request = ComponentRequest(source_kind="python", source="sample-tool==1.2.3")
        with patch("web_app.core.component_acquisition.subprocess.run", side_effect=fake_run) as run:
            acquired = self.acquirer.acquire(request, self.root / "staging")

        command = run.call_args.args[0]
        self.assertIn("--only-binary=:all:", command)
        manifest = json.loads((Path(acquired.source_root) / "component-resolution.json").read_text())
        normalization = json.loads((Path(acquired.source_root) / "component-normalization.json").read_text())
        self.assertEqual(manifest["coordinate"], "sample-tool==1.2.3")
        self.assertEqual(manifest["entry_points"], {"sample-tool": "sample_tool:main"})
        self.assertRegex(manifest["artifacts"][0]["sha256"], "^[0-9a-f]{64}$")
        self.assertEqual(normalization["extracted"]["identity"], {"name": "sample-tool", "version": "1.2.3"})
        self.assertEqual(normalization["decision"]["mode"], "adapted")
        self.assertEqual(normalization["extracted"]["blocked_behaviors"], ["source_builds"])
        self.assertEqual(normalization["alterations"][1]["id"], "python-metadata-launcher")
        plan = self.inspector.inspect(acquired, ComponentScope.global_)
        self.assertEqual((plan.runtime_kind, plan.entry_points), ("python", ("sample-tool",)))
        self.assertEqual(plan.normalization["decision"]["mode"], "adapted")
        self.assertEqual(plan.normalization["alterations"][1]["id"], "python-metadata-launcher")
        self.assertIn("process_launch", plan.effects)

    def test_node_coordinate_resolves_with_scripts_disabled_and_isolated_cache(self):
        def fake_run(command, **kwargs):
            project = Path(kwargs["cwd"])
            package = project / "node_modules" / "sample-tool"
            package.mkdir(parents=True)
            (package / "package.json").write_text(json.dumps({"name": "sample-tool", "version": "1.2.3", "bin": {"sample-tool": "cli.js"}}))
            (package / "cli.js").write_text("console.log('ok')")
            (project / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
                "node_modules/sample-tool": {"name": "sample-tool", "version": "1.2.3", "resolved": "https://registry.npmjs.org/sample-tool/-/sample-tool-1.2.3.tgz", "integrity": "sha512-dGVzdA=="}
            }}))
            return subprocess.CompletedProcess(command, 0, "", "")

        request = ComponentRequest(source_kind="node", source="sample-tool@1.2.3")
        with patch("web_app.core.component_acquisition.shutil.which", return_value=r"C:\Program Files\nodejs\npm.cmd"), patch("web_app.core.component_acquisition.subprocess.run", side_effect=fake_run) as run:
            acquired = self.acquirer.acquire(request, self.root / "staging")

        command = run.call_args.args[0]
        self.assertEqual(command[0], r"C:\Program Files\nodejs\npm.cmd")
        self.assertIn("--ignore-scripts", command)
        self.assertIn("--cache", command)
        manifest = json.loads((Path(acquired.source_root) / "component-resolution.json").read_text())
        normalization = json.loads((Path(acquired.source_root) / "component-normalization.json").read_text())
        self.assertEqual(manifest["entry_points"], {"sample-tool": "node_modules/sample-tool/cli.js"})
        self.assertEqual(manifest["packages"][0]["name"], "sample-tool")
        self.assertEqual(manifest["packages"][0]["integrity"], "sha512-dGVzdA==")
        self.assertEqual(normalization["extracted"]["identity"], {"name": "sample-tool", "version": "1.2.3"})
        self.assertEqual(normalization["extracted"]["blocked_behaviors"], ["lifecycle_scripts"])
        self.assertEqual(normalization["decision"]["mode"], "adapted")
        self.assertEqual(normalization["alterations"][1]["after"], "node <verified-bin-target>")
        plan = self.inspector.inspect(acquired, ComponentScope.global_)
        self.assertEqual((plan.runtime_kind, plan.entry_points), ("node", ("sample-tool",)))

    def test_inspector_rejects_unsafe_command_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"; source.mkdir()
            (source / "pyproject.toml").write_text("[project]\nname='bad'\nversion='1'\n[project.scripts]\n'../../escape'='bad:main'\n")
            acquired = AcquiredComponent(source_kind=ComponentSource.local, canonical_source=str(source), source_root=str(source), content_digest="sha256:" + "1" * 64)
            registry = ComponentRegistry(root / "registry.sqlite")
            try:
                with self.assertRaises(ValueError):
                    ComponentInspector(registry).inspect(acquired, ComponentScope.global_)
            finally:
                registry.close()
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry = ComponentRegistry(self.root / "registry.sqlite")
        self.acquirer = ComponentAcquirer()
        self.inspector = ComponentInspector(self.registry)

    def tearDown(self):
        self.registry.close()
        self.temporary.cleanup()

    def acquire_local(self, source: Path, kind="local"):
        request = ComponentRequest(source_kind=kind, source=str(source))
        return request, self.acquirer.acquire(request, self.root / "staging")

    def test_local_git_acquisition_records_exact_commit_and_digest(self):
        repository = self.root / "repo"
        repository.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
        (repository / "README.md").write_text("tool\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()

        request = ComponentRequest(source_kind="git", source=str(repository), requested_version=commit)
        acquired = self.acquirer.acquire(request, self.root / "staging")

        self.assertEqual(acquired.revision, commit)
        self.assertTrue(acquired.content_digest.startswith("sha256:"))
        self.assertTrue((Path(acquired.source_root) / "README.md").is_file())

    def test_inspector_recognizes_python_node_mcp_and_executable_entry_points(self):
        python = self.root / "python-tool"
        python.mkdir()
        (python / "pyproject.toml").write_text(
            '[project]\nname="sample-tool"\nversion="1.0.0"\n[project.scripts]\nsample="sample:main"\n',
            encoding="utf-8",
        )
        node = self.root / "node-tool"
        node.mkdir()
        (node / "package.json").write_text(json.dumps({"name": "node-tool", "version": "1.0.0", "bin": {"node-tool": "cli.js"}}), encoding="utf-8")
        mcp = self.root / "mcp-tool"
        mcp.mkdir()
        (mcp / "mcp_servers.json").write_text(json.dumps({"mcpServers": {"sample": {"command": "sample"}}}), encoding="utf-8")
        executable = self.root / "sample.exe"
        executable.write_bytes(b"MZ" + b"\0" * 62)

        cases = [
            (python, "python", ("sample",)),
            (node, "node", ("node-tool",)),
            (mcp, "mcp", ("sample",)),
            (executable, "executable", ("sample",)),
        ]
        for source, runtime_kind, entries in cases:
            with self.subTest(runtime_kind=runtime_kind):
                request, acquired = self.acquire_local(source)
                plan = self.inspector.inspect(acquired, request.scope)
                self.assertTrue(plan.executable)
                self.assertEqual(plan.runtime_kind, runtime_kind)
                self.assertEqual(plan.entry_points, entries)
                self.assertIn("filesystem_write", plan.effects)
                if runtime_kind in {"python", "node"}:
                    self.assertEqual("adapted", plan.normalization["decision"]["mode"])

    def test_unknown_repository_is_a_non_executable_resource(self):
        source = self.root / "notes"
        source.mkdir()
        (source / "README.md").write_text("reference only", encoding="utf-8")
        request, acquired = self.acquire_local(source)

        plan = self.inspector.inspect(acquired, request.scope)

        self.assertFalse(plan.executable)
        self.assertEqual(plan.runtime_kind, "resource")
        self.assertEqual(plan.entry_points, ())

    def test_local_source_cannot_claim_registry_resolution_or_forge_normalization(self):
        source = self.root / "untrusted-tool"
        source.mkdir()
        (source / "tool.cmd").write_text("@exit /b 0\n", encoding="utf-8")
        (source / "component-resolution.json").write_text(json.dumps({
            "format": 1, "ecosystem": "node", "coordinate": "trusted@9.9.9", "entry_points": {},
        }), encoding="utf-8")
        (source / "component-normalization.json").write_text(json.dumps({
            "format": 1, "ecosystem": "node", "coordinate": "trusted@9.9.9",
            "decision": {"mode": "native", "reason": "SIGNED AND SAFE"},
        }), encoding="utf-8")
        request, acquired = self.acquire_local(source)

        plan = self.inspector.inspect(acquired, request.scope)

        self.assertEqual("executable", plan.runtime_kind)
        self.assertEqual(("tool",), plan.entry_points)
        self.assertEqual("native", plan.normalization["decision"]["mode"])
        self.assertNotEqual("SIGNED AND SAFE", plan.normalization["decision"]["reason"])

    def test_archive_rejects_path_traversal(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../escape.txt", "bad")
        request = ComponentRequest(source_kind="archive", source=str(archive))

        with self.assertRaisesRegex(ValueError, "unsafe archive path"):
            self.acquirer.acquire(request, self.root / "staging")

    def test_invalid_package_coordinate_and_private_git_source_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "package coordinate"):
            self.acquirer.acquire(
                ComponentRequest(source_kind="python", source="bad package; command"), self.root / "staging"
            )
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            self.acquirer.acquire(
                ComponentRequest(source_kind="git", source="git@github.com:private/repo.git"), self.root / "staging"
            )

    def test_project_scope_is_preserved_in_installation_plan(self):
        source = self.root / "project-tool"
        source.mkdir()
        (source / "README.md").write_text("resource", encoding="utf-8")
        request = ComponentRequest(
            source_kind="local", source=str(source), scope=ComponentScope.project, project_id="project-a"
        )
        acquired = self.acquirer.acquire(request, self.root / "staging")

        plan = self.inspector.inspect(acquired, request.scope, project_id=request.project_id)

        self.assertEqual(plan.scope, ComponentScope.project)
        self.assertEqual(plan.project_id, "project-a")


if __name__ == "__main__":
    unittest.main()
