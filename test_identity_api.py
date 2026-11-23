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
        self.session_id = workspace.create_session().id
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
        manager = getattr(self.app.state, "component_manager", None)
        if manager is not None:
            manager.close()
        self.temporary.cleanup()

    def csrf(self):
        response = self.client.get("/api/identity/bootstrap")
        self.assertEqual(response.status_code, 200)
        return self.client.cookies.get("json_codr_csrf")

    def credential(self, kind: str, scopes: tuple[str, ...]):
        administrator = self.identity.list_users()[0]
        return self.identity.issue_credential(administrator.user_id, kind, f"test {kind}", scopes)

    def browser_headers(self, scopes: tuple[str, ...]):
        credential = self.credential("browser_session", scopes)
        self.client.cookies.set("json_codr_session", credential.token)
        return {"X-CSRF-Token": self.csrf()}

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

    def test_component_install_requires_scoped_credential_and_browser_csrf(self):
        """Removing credential checks or CSRF from component installation must fail this test."""
        path = "/api/components/install/missing"
        payload = {"approved_digest": "sha256:" + "0" * 64}

        unauthenticated = self.client.post(path, json=payload)
        self.assertEqual(unauthenticated.status_code, 401)

        wrong_scope = self.credential("service", ("git.commit",))
        forbidden = self.client.post(
            path,
            json=payload,
            headers={"Authorization": f"Bearer {wrong_scope.token}"},
        )
        self.assertEqual(forbidden.status_code, 403)

        browser_without_csrf = self.credential("browser_session", ("component.install",))
        self.client.cookies.set("json_codr_session", browser_without_csrf.token)
        self.assertEqual(self.client.post(path, json=payload).status_code, 403)

        service = self.credential("service", ("component.install",))
        accepted_service = self.client.post(
            path,
            json=payload,
            headers={"Authorization": f"Bearer {service.token}"},
        )
        self.assertEqual(accepted_service.status_code, 404)

        accepted_browser = self.client.post(
            path,
            json=payload,
            headers=self.browser_headers(("component.install",)),
        )
        self.assertEqual(accepted_browser.status_code, 404)

    def test_session_attachment_writes_require_session_scope_and_browser_csrf(self):
        """Removing either adjacent attachment guard must fail this test."""
        cases = (
            ("patch", f"/api/sessions/{self.session_id}/attachments/missing", {"included": True}),
            ("delete", f"/api/sessions/{self.session_id}/attachments/missing", None),
        )
        for method, path, payload in cases:
            with self.subTest(method=method):
                self.client.cookies.clear()
                request = getattr(self.client, method)
                arguments = {} if payload is None else {"json": payload}
                self.assertEqual(request(path, **arguments).status_code, 401)

                wrong_scope = self.credential("service", ("component.install",))
                self.assertEqual(
                    request(path, **arguments, headers={"Authorization": f"Bearer {wrong_scope.token}"}).status_code,
                    403,
                )

                browser_without_csrf = self.credential("browser_session", ("session.write",))
                self.client.cookies.set("json_codr_session", browser_without_csrf.token)
                self.assertEqual(request(path, **arguments).status_code, 403)

                service = self.credential("service", ("session.write",))
                self.assertEqual(
                    request(path, **arguments, headers={"Authorization": f"Bearer {service.token}"}).status_code,
                    404,
                )

                self.assertEqual(
                    request(path, **arguments, headers=self.browser_headers(("session.write",))).status_code,
                    404,
                )

    def test_component_disable_and_rollback_require_component_scope(self):
        """A missing component may fail later, but cannot bypass credential scope first."""
        client = TestClient(self.app, raise_server_exceptions=False)
        try:
            for path in ("/api/components/missing/disable", "/api/components/missing/rollback"):
                with self.subTest(path=path):
                    self.assertEqual(client.post(path).status_code, 401)
                    wrong_scope = self.credential("service", ("session.write",))
                    self.assertEqual(
                        client.post(path, headers={"Authorization": f"Bearer {wrong_scope.token}"}).status_code,
                        403,
                    )
                    service = self.credential("service", ("component.install",))
                    self.assertNotIn(
                        client.post(path, headers={"Authorization": f"Bearer {service.token}"}).status_code,
                        (401, 403),
                    )
        finally:
            client.close()

    def test_credential_kind_must_match_its_http_transport(self):
        """Treating a browser, CLI, or service token as another kind must stay unauthorized."""
        path = "/api/components/install/missing"
        payload = {"approved_digest": "sha256:" + "0" * 64}
        browser = self.credential("browser_session", ("component.install",))
        cli = self.credential("cli", ("component.install",))
        service = self.credential("service", ("component.install",))

        self.client.cookies.set("json_codr_session", service.token)
        self.assertEqual(self.client.post(path, json=payload, headers={"X-CSRF-Token": self.csrf()}).status_code, 401)
        self.assertEqual(
            self.client.post(path, json=payload, headers={"Authorization": f"Bearer {browser.token}"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(path, json=payload, headers={"Authorization": f"Bearer {cli.token}"}).status_code,
            401,
        )


if __name__ == "__main__":
    unittest.main()
