import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.security.bootstrap import BootstrapService
from web_app.security.accounts import AccountService
from web_app.security.passwords import PasswordHasher
from web_app.security.sessions import SessionService
from web_app.security.store import SecurityStore
from web_app.workspace import WorkspaceService


class _Service:
    pass


class AuthenticationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        store = SecurityStore(root / "security.sqlite3")
        accounts = AccountService(store, PasswordHasher())
        sessions = SessionService(store)
        bootstrap = BootstrapService(store, accounts)
        self.claim = bootstrap.issue_initial_claim()
        app = create_app(
            _Service(), workspace=WorkspaceService(root / "workspace"), optimized=False,
            security_store=store, account_service=accounts, session_service=sessions, bootstrap_service=bootstrap,
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_bootstrap_login_logout_and_server_derived_session_identity(self) -> None:
        response = self.client.post("/api/auth/bootstrap", json={
            "claim": self.claim, "username": "Administrator", "password": "correct horse battery staple"
        })
        self.assertEqual(response.status_code, 201, response.text)
        login = self.client.post("/api/auth/login", json={"username": "Administrator", "password": "correct horse battery staple"})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertNotIn("account_id", login.text)
        self.assertIn("HttpOnly", login.headers["set-cookie"])
        current = self.client.get("/api/auth/session")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["username"], "Administrator")
        logout = self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(self.client.get("/api/auth/session").status_code, 401)


if __name__ == "__main__":
    unittest.main()
