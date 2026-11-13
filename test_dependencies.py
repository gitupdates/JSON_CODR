import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.attachments import AttachmentService
from web_app.dependencies import DependencyService
from web_app.workspace import WorkspaceService


class FakeOllamaService:
    async def health(self):
        return {"ollama": True}

    async def list_models(self):
        return []


class DependencyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceService(Path(self.temporary_directory.name))
        self.session = self.workspace.create_session()
        self.attachments = AttachmentService(self.workspace)
        self.dependencies = DependencyService(self.attachments)

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

    def test_package_manifest_proposes_npm_install_command(self):
        payload = json.dumps(
            {"dependencies": {"react": "^19.0.0", "@scope/tool": "1.2.0"}, "devDependencies": {"vite": "^7.0.0"}}
        )
        self.attachments.import_text(self.session.id, payload, "package.json")

        suggestions = self.dependencies.detect(self.session.id)

        self.assertEqual(suggestions[0].command, "npm install react@^19.0.0 @scope/tool@1.2.0 vite@^7.0.0")
        self.assertEqual(suggestions[0].ecosystem, "node")

    def test_http_returns_dependency_suggestions_for_confirmation(self):
        self.attachments.import_text(self.session.id, "httpx>=0.27", "requirements.txt")
        client = TestClient(create_app(FakeOllamaService(), self.workspace, self.attachments))

        response = client.get(f"/api/sessions/{self.session.id}/dependencies")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["command"], "python -m pip install 'httpx>=0.27'")
        self.assertFalse(response.json()[0]["automatic"])


if __name__ == "__main__":
    unittest.main()
