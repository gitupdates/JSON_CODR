import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.workspace import WorkspaceService


class FakeService:
    async def health(self):
        return {"ollama": True}


class FakeGitHubCli:
    def commit_local_changes(self, project_root: str, message: str):
        return {"project_root": project_root, "message": message, "status": "committed"}

    def push_local_changes(self, project_root: str):
        return {"project_root": project_root, "status": "pushed"}

    def status(self):
        return {"authenticated": True}


class GitHubMutationApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        workspace = WorkspaceService(Path(self.temporary.name) / "data")
        self.app = create_app(FakeService(), workspace=workspace, github_cli=FakeGitHubCli())
        self.identity = self.app.state.identity
        administrator = self.identity.bootstrap("development", "Administrator").user
        self.user_id = administrator.user_id
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def credential(self, kind: str, scopes: tuple[str, ...]):
        return self.identity.issue_credential(self.user_id, kind, f"test {kind}", scopes)

    def browser_headers(self, scopes: tuple[str, ...]):
        credential = self.credential("browser_session", scopes)
        self.client.cookies.set("json_codr_session", credential.token)
        csrf = self.client.get("/api/identity/bootstrap").cookies["json_codr_csrf"]
        return {"X-CSRF-Token": csrf}

    def test_commit_and_push_require_their_own_scopes_and_browser_csrf(self):
        """Changing either route to accept the static header or a neighbouring Git scope must fail."""
        cases = (
            ("/api/github/local/commit", {"project_root": str(self.project), "message": "test", "confirmed": True}, "git.commit", "committed", 201),
            ("/api/github/local/push", {"project_root": str(self.project), "confirmed": True}, "git.push", "pushed", 200),
        )
        for path, payload, scope, status, expected_status in cases:
            with self.subTest(path=path):
                self.client.cookies.clear()
                self.assertEqual(self.client.post(path, json=payload).status_code, 401)

                wrong_scope = self.credential("service", ("git.edit",))
                self.assertEqual(
                    self.client.post(
                        path,
                        json=payload,
                        headers={"Authorization": f"Bearer {wrong_scope.token}"},
                    ).status_code,
                    403,
                )

                service = self.credential("service", (scope,))
                accepted_service = self.client.post(
                    path,
                    json=payload,
                    headers={"Authorization": f"Bearer {service.token}"},
                )
                self.assertEqual(accepted_service.status_code, expected_status)
                self.assertEqual(accepted_service.json()["status"], status)

                accepted_browser = self.client.post(
                    path,
                    json=payload,
                    headers=self.browser_headers((scope,)),
                )
                self.assertEqual(accepted_browser.status_code, expected_status)

    def test_read_only_github_compatibility_header_is_deprecated(self):
        response = self.client.get("/api/github/status", headers={"X-JSON-CODR": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("deprecation"), "true")


if __name__ == "__main__":
    unittest.main()
