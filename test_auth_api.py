import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from web_app.app import create_app
from web_app.security.accounts import ADMINISTRATOR_ACCOUNT_ID, AccountService
from web_app.security.bootstrap import BootstrapService
from web_app.security.passwords import PasswordHasher
from web_app.security.sessions import SESSION_COOKIE_NAME, SessionService
from web_app.security.store import SecurityStore
from web_app.workspace import WorkspaceService


class _Service:
    pass


class AuthenticationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = SecurityStore(self.root / "security.sqlite3")
        self.accounts = AccountService(self.store, PasswordHasher())
        self.sessions = SessionService(self.store, secure_cookies=False)
        self.bootstrap = BootstrapService(self.store, self.accounts)
        self.claim = self.bootstrap.issue_initial_claim()
        app = create_app(
            _Service(), workspace=WorkspaceService(self.root / "workspace"), optimized=False,
            security_store=self.store, account_service=self.accounts, session_service=self.sessions,
            bootstrap_service=self.bootstrap,
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _bootstrap_administrator(self):
        response = self.client.post("/api/auth/bootstrap", json={
            "claim": self.claim, "username": "Administrator", "password": "correct horse battery staple"
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response

    def test_explicit_bootstrap_accepts_only_administrator_and_immediately_authenticates(self) -> None:
        rejected = self.client.post("/api/auth/bootstrap", json={
            "claim": self.claim, "username": "administrator", "password": "correct horse battery staple"
        })
        self.assertEqual(rejected.status_code, 403, rejected.text)

        response = self._bootstrap_administrator()
        self.assertEqual(set(response.json()), {"username", "status"})
        self.assertNotIn("account_id", response.text)
        self.assertNotIn("token", response.text.casefold())
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        current = self.client.get("/api/auth/session")
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["username"], "Administrator")

    def test_authenticated_recent_administrator_creates_pending_account_with_one_no_store_claim(self) -> None:
        self._bootstrap_administrator()
        response = self.client.post("/api/auth/accounts", json={"username": "Pending User"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        payload = response.json()
        self.assertEqual(set(payload), {"account_id", "username", "enrollment_claim"})
        self.assertEqual(payload["username"], "Pending User")
        self.assertEqual(self.accounts.get_account(UUID(payload["account_id"])).status, "pending")
        with self.store.transaction() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM auth_claims WHERE account_id = ? AND purpose = 'enrollment' AND consumed_at IS NULL",
                    (payload["account_id"],),
                ).fetchone()[0],
                1,
            )

    def test_body_actor_spoof_is_rejected_and_cannot_authorize_account_creation(self) -> None:
        self._bootstrap_administrator()
        ordinary = self.accounts.create_account("Ordinary", "correct horse battery staple")
        ordinary_session = self.sessions.create(ordinary.account_id)
        self.client.cookies.clear()
        self.client.cookies.set(SESSION_COOKIE_NAME, ordinary_session.token)
        with self.store.transaction() as connection:
            before = connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]

        response = self.client.post("/api/auth/accounts", json={
            "username": "Spoofed User",
            "actor_account_id": str(ADMINISTRATOR_ACCOUNT_ID),
            "administrator_id": str(ADMINISTRATOR_ACCOUNT_ID),
        })
        self.assertEqual(response.status_code, 422, response.text)
        with self.store.transaction() as connection:
            after = connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM accounts WHERE username_casefold = 'spoofed user'").fetchone()[0], 0
            )
        self.assertEqual(after, before)

    def test_non_admin_and_stale_auth_sessions_cannot_issue_claims(self) -> None:
        self._bootstrap_administrator()
        ordinary = self.accounts.create_account("Ordinary", "correct horse battery staple")
        ordinary_session = self.sessions.create(ordinary.account_id)
        self.client.cookies.clear()
        self.client.cookies.set(SESSION_COOKIE_NAME, ordinary_session.token)
        denied = self.client.post("/api/auth/accounts", json={"username": "Denied Non Admin"})
        self.assertEqual(denied.status_code, 403, denied.text)

        stale_time = datetime.now(timezone.utc) - timedelta(minutes=6)
        stale_session = self.sessions.create(ADMINISTRATOR_ACCOUNT_ID, now=stale_time)
        self.client.cookies.clear()
        self.client.cookies.set(SESSION_COOKIE_NAME, stale_session.token)
        stale = self.client.post("/api/auth/accounts", json={"username": "Denied Stale Admin"})
        self.assertEqual(stale.status_code, 403, stale.text)

    def test_enrollment_reissue_and_reset_use_cookie_actor_and_reset_revokes_target_session(self) -> None:
        self._bootstrap_administrator()
        created = self.client.post("/api/auth/accounts", json={"username": "Lifecycle User"})
        self.assertEqual(created.status_code, 201, created.text)
        account_id = created.json()["account_id"]
        first_claim = created.json()["enrollment_claim"]

        reissued = self.client.post(f"/api/auth/accounts/{account_id}/enrollment-claim")
        self.assertEqual(reissued.status_code, 200, reissued.text)
        self.assertEqual(reissued.headers["cache-control"], "no-store")
        second_claim = reissued.json()["enrollment_claim"]
        self.assertNotEqual(first_claim, second_claim)
        self.assertEqual(
            self.client.post(
                "/api/auth/enrollment", json={"claim": first_claim, "password": "rejected old password"}
            ).status_code,
            403,
        )
        enrolled = self.client.post(
            "/api/auth/enrollment", json={"claim": second_claim, "password": "chosen lifecycle password"}
        )
        self.assertEqual(enrolled.status_code, 204, enrolled.text)

        target = self.accounts.authenticate("Lifecycle User", "chosen lifecycle password")
        target_session = self.sessions.create(target.account_id)
        reset = self.client.post(f"/api/auth/accounts/{account_id}/reset-claim")
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.headers["cache-control"], "no-store")
        self.assertEqual(set(reset.json()), {"reset_claim"})
        self.assertIsNone(self.sessions.lookup(target_session.token))

    def test_secure_cookie_configuration_is_symmetric_for_set_and_delete(self) -> None:
        for secure in (False, True):
            with self.subTest(secure=secure):
                root = self.root / ("secure" if secure else "insecure")
                store = SecurityStore(root / "security.sqlite3")
                accounts = AccountService(store, PasswordHasher())
                sessions = SessionService(store, secure_cookies=secure)
                bootstrap = BootstrapService(store, accounts)
                claim = bootstrap.issue_initial_claim()
                app = create_app(
                    _Service(), workspace=WorkspaceService(root / "workspace"), optimized=False,
                    security_store=store, account_service=accounts, session_service=sessions,
                    bootstrap_service=bootstrap,
                )
                client = TestClient(app, base_url="https://testserver" if secure else "http://testserver")
                created = client.post("/api/auth/bootstrap", json={
                    "claim": claim, "username": "Administrator", "password": "correct horse battery staple"
                })
                self.assertEqual(created.status_code, 201, created.text)
                deleted = client.post("/api/auth/logout")
                self.assertEqual(deleted.status_code, 204, deleted.text)
                for header in (created.headers["set-cookie"], deleted.headers["set-cookie"]):
                    self.assertIn("HttpOnly", header)
                    self.assertIn("Path=/", header)
                    self.assertIn("SameSite=strict", header)
                    self.assertEqual("; secure" in header.casefold(), secure)


if __name__ == "__main__":
    unittest.main()
