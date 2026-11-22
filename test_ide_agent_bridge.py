import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _FixtureHandler(BaseHTTPRequestHandler):
    requests = []

    def do_GET(self):
        self.requests.append(("GET", self.path, None))
        if self.path == "/api/health":
            self._send(200, {"status": "ready", "app_version": "V1.3.2"})
        elif self.path == "/api/models":
            self._send(200, [{"name": "qwen3.5:9b", "installed": True}])
        else:
            self._send(404, {"detail": "missing"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.requests.append(("POST", self.path, body))
        if self.path == "/api/workspace/tasks":
            self._send(202, {
                "task_id": "task-1",
                "requested_engine": "borg",
                "effective_engine": "borg",
                "requested_model": body["model_selection"],
                "effective_model": "qwen3.5:9b",
                "route": "native",
                "status": "approval_required",
                "warnings": [],
                "result": {"task": {"status": "awaiting_approval"}},
                "artifact_references": [],
            })
        else:
            self._send(400, {"detail": "bad request"})

    def log_message(self, format, *args):
        return

    def _send(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class BorgClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _FixtureHandler.requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _client_types(self):
        try:
            from web_app.integrations.borg_client import BorgClient, BorgClientError
        except ImportError as error:
            self.fail(f"BORG client integration is missing: {error}")
        return BorgClient, BorgClientError

    def test_reads_real_health_and_model_payloads(self):
        BorgClient, _ = self._client_types()
        client = BorgClient(self.base_url)

        self.assertEqual(client.health()["app_version"], "V1.3.2")
        self.assertEqual(client.models()[0]["name"], "qwen3.5:9b")

    def test_workspace_task_preserves_async_approval_state(self):
        BorgClient, _ = self._client_types()
        client = BorgClient(self.base_url)

        result = client.run_workspace_task(
            session_id="session-1",
            project_root="D:/projects/example",
            prompt="Inspect the project",
            model_selection="auto",
        )

        self.assertEqual(result["status"], "approval_required")
        method, path, body = _FixtureHandler.requests[-1]
        self.assertEqual((method, path), ("POST", "/api/workspace/tasks"))
        self.assertEqual(body["engine_id"], "borg")
        self.assertEqual(body["context_references"], [])

    def test_api_error_exposes_bounded_service_detail(self):
        BorgClient, BorgClientError = self._client_types()
        client = BorgClient(self.base_url)

        with self.assertRaisesRegex(BorgClientError, "JSON_CODR API returned 404: missing"):
            client._request("GET", "/api/not-present")

    def test_unreachable_service_raises_bridge_error(self):
        BorgClient, BorgClientError = self._client_types()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        client = BorgClient(f"http://127.0.0.1:{port}", timeout_seconds=0.2)

        with self.assertRaisesRegex(BorgClientError, "JSON_CODR service is unavailable"):
            client.health()


if __name__ == "__main__":
    unittest.main()
