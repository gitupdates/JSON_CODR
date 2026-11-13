import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.attachments import AttachmentService
from web_app.dependencies import DependencyPreflight, DependencyService
from web_app.workspace import WorkspaceService


class FakeOllamaService:
    async def health(self):
        return {"ollama": True}

    async def list_models(self):
        return []


class FakePreflight:
    def __init__(self, missing_python=None, missing_node=None):
        self.python_result = missing_python
        self.node_result = missing_node

    def missing_python(self, specs):
        return list(specs) if self.python_result is None else list(self.python_result)

    def missing_node(self, packages, cwd):
        return list(packages) if self.node_result is None else list(self.node_result)


class DependencyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceService(Path(self.temporary_directory.name))
        self.session = self.workspace.create_session()
        self.attachments = AttachmentService(self.workspace)
        self.dependencies = DependencyService(
            self.attachments,
            preflight=FakePreflight(),
            install_root=Path(self.temporary_directory.name),
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_requirements_manifest_proposes_bounded_pip_command(self):
        self.attachments.import_text(
            self.session.id,
            "requests==2.32.3\nfastapi>=0.115\n-r other.txt\nevil; whoami\n",
            "requirements.txt",
        )

        suggestions = self.dependencies.detect(self.session.id)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(
            suggestions[0].command,
            "python -m pip install 'requests==2.32.3' 'fastapi>=0.115'",
        )
        self.assertEqual(suggestions[0].ecosystem, "python")
        self.assertTrue(suggestions[0].automatic)

    def test_package_manifest_proposes_npm_install_command(self):
        payload = json.dumps(
            {"dependencies": {"react": "^19.0.0", "@scope/tool": "1.2.0"}, "devDependencies": {"vite": "^7.0.0"}}
        )
        self.attachments.import_text(self.session.id, payload, "package.json")

        suggestions = self.dependencies.detect(self.session.id)

        self.assertEqual(suggestions[0].command, "npm install react@^19.0.0 @scope/tool@1.2.0 vite@^7.0.0")
        self.assertEqual(suggestions[0].ecosystem, "node")

    def test_service_omits_satisfied_dependencies_and_rejects_invalid_lines(self):
        self.dependencies = DependencyService(
            self.attachments,
            preflight=FakePreflight(missing_python=["missing-package>=1"]),
        )
        self.attachments.import_text(
            self.session.id,
            "installed-package>=1\nmissing-package>=1\nevil; whoami\n-r other.txt\n",
            "requirements.txt",
        )

        suggestions = self.dependencies.detect(self.session.id)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].command, "python -m pip install 'missing-package>=1'")
        self.assertTrue(suggestions[0].automatic)

    def test_service_returns_no_suggestion_when_every_dependency_is_satisfied(self):
        self.dependencies = DependencyService(self.attachments, preflight=FakePreflight(missing_python=[]))
        self.attachments.import_text(self.session.id, "installed-package>=1", "requirements.txt")

        self.assertEqual(self.dependencies.detect(self.session.id), [])

    def test_http_returns_automatic_suggestion_for_missing_dependency(self):
        self.attachments.import_text(self.session.id, "json-codr-definitely-missing>=999", "requirements.txt")
        client = TestClient(create_app(FakeOllamaService(), self.workspace, self.attachments))

        response = client.get(f"/api/sessions/{self.session.id}/dependencies")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()[0]["command"],
            "python -m pip install 'json-codr-definitely-missing>=999'",
        )
        self.assertTrue(response.json()[0]["automatic"])


class DependencyPreflightTests(unittest.TestCase):
    @patch("web_app.dependencies.metadata.version")
    def test_python_returns_only_absent_or_incompatible_specs(self, version):
        versions = {"satisfied": "2.5", "incompatible": "1.0"}

        def lookup(name):
            if name not in versions:
                raise LookupError(name)
            return versions[name]

        version.side_effect = lookup

        missing = DependencyPreflight().missing_python(
            ["satisfied>=2", "incompatible>=2", "absent==1.0"]
        )

        self.assertEqual(missing, ["incompatible>=2", "absent==1.0"])

    @patch("web_app.dependencies.shutil.which", return_value="npm")
    @patch("web_app.dependencies.subprocess.run")
    def test_node_checks_argument_arrays_and_returns_failed_ranges(self, run, which):
        run.side_effect = [
            CompletedProcess([], 0, stdout="{}", stderr=""),
            CompletedProcess([], 1, stdout="{}", stderr=""),
            CompletedProcess([], 0, stdout="{}", stderr=""),
        ]
        packages = ["react@^19.0.0", "vite@^7.0.0", "@scope/tool@1.2.0"]
        root = Path("C:/project")

        missing = DependencyPreflight().missing_node(packages, root)

        self.assertEqual(missing, ["vite@^7.0.0"])
        self.assertEqual(run.call_count, 3)
        for package, call in zip(packages, run.call_args_list):
            self.assertEqual(call.args[0], ["npm", "ls", package, "--depth=0", "--json"])
            self.assertEqual(call.kwargs["cwd"], root)
            self.assertFalse(call.kwargs["shell"])
            self.assertEqual(call.kwargs["timeout"], 10)

    @patch("web_app.dependencies.shutil.which", return_value=None)
    @patch("web_app.dependencies.subprocess.run")
    def test_node_treats_missing_npm_as_missing(self, run, which):
        packages = ["first@1", "second@2"]

        self.assertEqual(DependencyPreflight().missing_node(packages, Path("C:/project")), packages)
        run.assert_not_called()

    @patch("web_app.dependencies.shutil.which", return_value="npm")
    @patch("web_app.dependencies.subprocess.run", side_effect=TimeoutExpired("npm", 10))
    def test_node_treats_timeout_as_missing(self, run, which):
        self.assertEqual(DependencyPreflight().missing_node(["first@1"], Path("C:/project")), ["first@1"])


if __name__ == "__main__":
    unittest.main()
