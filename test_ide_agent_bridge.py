import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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


class _FakeBorgClient:
    def health(self):
        return {"status": "ready", "app_version": "V1.3.2"}

    def models(self):
        return [{"name": "qwen3.5:9b", "installed": True}]

    def run_workspace_task(self, **arguments):
        return {"status": "approval_required", "arguments": arguments}


class McpServerTests(unittest.TestCase):
    def _server(self):
        try:
            from web_app.integrations.mcp_server import McpServer
        except ImportError as error:
            self.fail(f"MCP bridge is missing: {error}")
        return McpServer(_FakeBorgClient())

    def test_initializes_and_lists_three_bounded_tools(self):
        server = self._server()

        initialized = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(
            [tool["name"] for tool in listed["result"]["tools"]],
            ["json_codr.health", "json_codr.models", "json_codr.run_workspace_task"],
        )

    def test_calls_real_client_methods_and_preserves_task_state(self):
        server = self._server()
        request = {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "json_codr.run_workspace_task", "arguments": {
                "session_id": "session-1", "project_root": "D:/project",
                "prompt": "Inspect", "model_selection": "auto",
            }},
        }

        result = server.handle(request)["result"]

        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["status"], "approval_required")
        self.assertEqual(result["structuredContent"]["arguments"]["session_id"], "session-1")

    def test_rejects_unknown_tools_and_arguments_before_client_call(self):
        server = self._server()
        unknown_tool = server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "json_codr.delete_everything", "arguments": {}},
        })
        unknown_argument = server.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "json_codr.health", "arguments": {"extra": True}},
        })

        self.assertEqual(unknown_tool["error"]["code"], -32602)
        self.assertEqual(unknown_argument["error"]["code"], -32602)

    def test_malformed_request_returns_protocol_error(self):
        response = self._server().handle({"jsonrpc": "2.0", "id": 6, "params": {}})

        self.assertEqual(response["error"]["code"], -32600)


class AdapterPackageTests(unittest.TestCase):
    root = Path(__file__).parent

    def _json(self, path):
        if not path.is_file():
            self.fail(f"Adapter package file is missing: {path.relative_to(self.root)}")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_vscode_plugin_uses_portable_manifest_and_borg_bridge(self):
        plugin_root = self.root / "integrations" / "vscode-json-codr"
        manifest = self._json(plugin_root / "plugin.json")
        mcp = self._json(plugin_root / "mcp.json")

        self.assertEqual(manifest["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertEqual(manifest["name"], "json-codr")
        server = mcp["mcpServers"]["json-codr-borg"]
        self.assertEqual(mcp["$schema"], "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json")
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["args"][:2], ["-m", "web_app.integrations.mcp_server"])
        self.assertIn("JSON_CODR_URL", server["env"])
        self.assertEqual(server["env"].get("PYTHONPATH"), "${PLUGIN_ROOT}/../..")
        self.assertTrue((plugin_root / "com.github.copilot/agents/json-codr.agent.md").is_file())
        skill = (plugin_root / "skills/json-codr-workspace/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: json-codr-workspace", skill)

    def test_visual_studio_template_launches_the_same_bridge(self):
        root = self.root / "integrations" / "visual-studio-2022"
        config = self._json(root / ".mcp.json")
        server = config["servers"]["json-codr-borg"]

        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["args"][:2], ["-m", "web_app.integrations.mcp_server"])
        self.assertTrue((root / "README.md").is_file())

    def test_generic_manifest_matches_its_closed_schema(self):
        from web_app.integrations.mcp_server import TOOLS

        root = self.root / "integrations" / "generic"
        manifest = self._json(root / "adapter-manifest.json")
        schema = self._json(root / "adapter-manifest.schema.json")

        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(set(manifest), set(schema["required"]))
        self.assertEqual(manifest["protocol_version"], "2025-06-18")
        self.assertEqual(manifest["transports"], ["stdio"])
        self.assertEqual(manifest["command"][1:3], ["-m", "web_app.integrations.mcp_server"])
        self.assertEqual(manifest["tools"], [tool["name"] for tool in TOOLS])


if __name__ == "__main__":
    unittest.main()
