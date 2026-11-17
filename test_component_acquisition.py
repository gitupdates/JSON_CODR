import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from web_app.core.component_acquisition import AcquiredComponent, ComponentAcquirer
from web_app.core.component_inspection import ComponentInspector
from web_app.core.component_registry import ComponentRegistry, ComponentRequest, ComponentScope, ComponentSource


class ComponentAcquisitionTests(unittest.TestCase):
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

    def test_unknown_repository_is_a_non_executable_resource(self):
        source = self.root / "notes"
        source.mkdir()
        (source / "README.md").write_text("reference only", encoding="utf-8")
        request, acquired = self.acquire_local(source)

        plan = self.inspector.inspect(acquired, request.scope)

        self.assertFalse(plan.executable)
        self.assertEqual(plan.runtime_kind, "resource")
        self.assertEqual(plan.entry_points, ())

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
