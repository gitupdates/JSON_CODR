import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.core.auth import LocalRequestEvidence
from web_app.workspace import WorkspaceService


class FakeService:
    async def health(self):
        return {"ollama": True}


class IdentityApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        workspace = WorkspaceService(Path(self.temporary.name))
        self.app = create_app(FakeService(), workspace=workspace)
        self.identity = self.app.state.identity
        self.identity.bootstrap("development", "Administrator")
        self.identity.confirm_development_bypass(
            LocalRequestEvidence(
                peer_host="127.0.0.1",
                host="127.0.0.1",
                server_host="127.0.0.1",
                headers={},
            ),
            configured_host="127.0.0.1",
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def csrf(self):
        response = self.client.get("/api/identity/bootstrap")
        self.assertEqual(response.status_code, 200)
        return self.client.cookies.get("json_codr_csrf")

    def test_login_requires_csrf_and_returns_only_account_metadata(self):
        denied = self.client.post(
            "/api/identity/login", json={"username": "Administrator", "password": ""}
        )
        self.assertEqual(denied.status_code, 403)

        csrf = self.csrf()
        response = self.client.post(
            "/api/identity/login",
            headers={"X-CSRF-Token": csrf},
            json={"username": "Administrator", "password": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "Administrator")
        self.assertNotIn("token", response.text.casefold())
        self.assertIn("json_codr_session", response.cookies)

    def test_login_failure_is_generic_and_session_supports_logout(self):
        csrf = self.csrf()
        failure = self.client.post(
            "/api/identity/login",
            headers={"X-CSRF-Token": csrf},
            json={"username": "missing", "password": "wrong"},
        )
        self.assertEqual(failure.status_code, 401)
        self.assertEqual(failure.json()["detail"], "Invalid username or password")

        login = self.client.post(
            "/api/identity/login",
            headers={"X-CSRF-Token": csrf},
            json={"username": "Administrator", "password": ""},
        )
        self.assertEqual(login.status_code, 200)
        account = self.client.get("/api/identity/account")
        self.assertEqual(account.status_code, 200)
        self.assertIn("administrator", account.json()["roles"])

        logout = self.client.post("/api/identity/logout", headers={"X-CSRF-Token": csrf})
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(self.client.get("/api/identity/account").status_code, 401)


if __name__ == "__main__":
    unittest.main()
