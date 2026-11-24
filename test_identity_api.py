import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from web_app.app import create_app
from web_app.core.auth import LocalRequestEvidence
from web_app.core.identity import MUTATION_SCOPES
from web_app.core.mutation_inventory import inventory_mutation_routes
from web_app.workspace import WorkspaceService


class FakeService:
    async def health(self):
        return {"ollama": True}


class StoppedTerminals:
    def list(self):
        return [{"id": "terminal-1", "status": "stopped"}]

    def get(self, terminal_id):
        if terminal_id != "terminal-1":
            raise KeyError(terminal_id)
        return SimpleNamespace(status="stopped", cwd=".")

    def read_after(self, terminal_id, after_sequence, timeout):
        return []


class IdentityApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        workspace = WorkspaceService(Path(self.temporary.name))
        self.session_id = workspace.create_session().id
        self.app = create_app(FakeService(), workspace=workspace, terminals=StoppedTerminals())
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

    def test_mutation_middleware_returns_json_auth_error(self):
        client = TestClient(self.app, raise_server_exceptions=False)
        try:
            response = client.post(
                "/api/workspace/tasks",
                json={
                    "project_root": ".",
                    "session_id": self.session_id,
                    "engine_id": "borg",
                    "model_selection": "auto",
                    "prompt": "Inspect the project",
                    "context_references": [],
                },
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["content-type"], "application/json")
            self.assertEqual(response.json(), {"detail": "Authentication required"})
        finally:
            client.close()

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

    def test_mcp_mutation_boundary_requires_agent_scope_and_csrf(self):
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        self.client.cookies.clear()
        self.assertEqual(self.client.post("/mcp", json=payload).status_code, 401)

        wrong_scope = self.credential("service", ("session.write",))
        self.assertEqual(
            self.client.post(
                "/mcp", json=payload,
                headers={"Authorization": f"Bearer {wrong_scope.token}"},
            ).status_code,
            403,
        )

        browser = self.credential("browser_session", ("agent.launch",))
        self.client.cookies.set("json_codr_session", browser.token)
        self.assertEqual(self.client.post("/mcp", json=payload).status_code, 403)

        service = self.credential("service", ("agent.launch",))
        with TestClient(self.app, client=("127.0.0.1", 50001)) as loopback:
            accepted = loopback.post(
                "/mcp", json=payload,
                headers={"Authorization": f"Bearer {service.token}"},
            )
            self.assertEqual(accepted.status_code, 200)

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
        cli_without_scope = self.credential("cli", ("git.commit",))
        self.assertEqual(
            self.client.post(path, json=payload, headers={"Authorization": f"Bearer {cli_without_scope.token}"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(path, json=payload, headers={"Authorization": f"Bearer {cli.token}"}).status_code,
            404,
        )

    def test_terminal_listing_and_socket_require_scoped_authenticated_browser_session(self):
        """Terminal writes must authenticate before the WebSocket accepts an input-capable connection."""
        socket_path = "/ws/terminals/terminal-1"
        origin = {"origin": "http://testserver"}
        self.assertEqual(self.client.get("/api/terminals").status_code, 401)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(socket_path, headers=origin):
                pass

        browser_bearer = self.credential("browser_session", ("terminal.write",))
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                socket_path,
                headers={**origin, "Authorization": f"Bearer {browser_bearer.token}"},
            ):
                pass

        wrong_scope = self.credential("browser_session", ("agent.launch",))
        self.client.cookies.set("json_codr_session", wrong_scope.token)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(socket_path, headers=origin):
                pass

        self.client.cookies.clear()
        valid = self.credential("browser_session", ("terminal.write",))
        self.client.cookies.set("json_codr_session", valid.token)
        csrf = self.csrf()
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(socket_path, headers=origin):
                pass

        with self.client.websocket_connect(
            socket_path,
            headers=origin,
            subprotocols=[f"json-codr-csrf.{csrf}"],
        ) as socket:
            self.assertEqual(socket.receive_json()["type"], "exit")
        self.assertEqual(self.client.get("/api/terminals").status_code, 200)

    def test_update_status_is_authenticated_read_only_and_permissions_are_server_derived(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/updates").status_code, 401)

        self.browser_headers(())
        readonly = self.client.get("/api/updates")
        self.assertEqual(readonly.status_code, 200)
        self.assertFalse(readonly.json()["automatic_mode"]["enabled"])
        self.assertFalse(readonly.json()["automatic_mode"]["ready"])
        self.assertEqual(
            readonly.json()["permissions"],
            {"propose": False, "quarantine": False, "activate": False, "rollback": False},
        )

        self.client.cookies.clear()
        self.browser_headers(("system.update", "system.activate", "system.rollback"))
        permitted = self.client.get("/api/updates")
        self.assertEqual(permitted.status_code, 200)
        self.assertEqual(
            permitted.json()["permissions"],
            {"propose": True, "quarantine": True, "activate": True, "rollback": True},
        )

    def test_default_update_controller_has_a_lazy_trusted_verifier(self):
        """A configured verification profile must be reachable from the default controller."""
        controller = self.app.state.autonomous_updates
        self.assertIsNotNone(getattr(controller, "_verifier", None))
        self.assertEqual(
            controller._launcher.pointer_store.pointer_path,
            Path(self.temporary.name).resolve() / "launcher" / "pointer" / "active-build.json",
        )

    def test_update_mutations_reject_legacy_header_and_enforce_reverse_action_scopes(self):
        self.client.cookies.clear()
        legacy = self.client.post(
            "/api/updates/candidates",
            json={"profile_id": "self-update", "prompt": "candidate"},
            headers={"X-JSON-CODR": "1"},
        )
        self.assertEqual(legacy.status_code, 401)

        update_only = self.browser_headers(("system.update",))
        self.assertEqual(
            self.client.post("/api/updates/candidates/missing/activate", headers=update_only).status_code,
            403,
        )
        self.client.cookies.clear()
        activate = self.browser_headers(("system.activate",))
        self.assertEqual(
            self.client.post("/api/updates/candidates/missing/activate", headers=activate).status_code,
            404,
        )
        self.client.cookies.clear()
        rollback = self.browser_headers(("system.rollback",))
        self.assertEqual(
            self.client.post("/api/updates/candidates/missing/rollback", headers=rollback).status_code,
            404,
        )
        self.client.cookies.clear()
        quarantine = self.browser_headers(("system.update",))
        self.assertEqual(
            self.client.post(
                "/api/updates/candidates/missing/quarantine",
                json={"reason": "review"}, headers=quarantine,
            ).status_code,
            404,
        )

    def test_generated_mutation_inventory_has_no_unassigned_write_route(self):
        inventory = self.app.state.mutation_route_inventory
        self.assertTrue(inventory)
        self.assertFalse([item for item in inventory if item.scope is None])
        self.assertFalse([item for item in inventory if item.scope not in MUTATION_SCOPES])
        assignments = {(item.method, item.path): (item.classification, item.scope) for item in inventory}
        self.assertEqual(
            assignments[("POST", "/api/updates/candidates/{candidate_id}/activate")],
            ("autonomous_mutation", "system.activate"),
        )
        self.assertEqual(
            assignments[("POST", "/api/updates/candidates/{candidate_id}/rollback")],
            ("autonomous_mutation", "system.rollback"),
        )
        self.assertIn(("POST", "/api/components/install/{plan_id}"), assignments)

        from fastapi import FastAPI
        future = FastAPI()

        @future.post("/api/future-write")
        def future_write():
            return {}

        with self.assertRaisesRegex(ValueError, "unassigned mutation route"):
            inventory_mutation_routes(future)


if __name__ == "__main__":
    unittest.main()
