import json
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from web_app.core.mcp_stdio_backend import (
    LeasedReaBackend,
    McpServerConfig,
    StdioMcpBackend,
    build_mcp_adapters,
    load_mcp_server_configs,
)
from web_app.core.rea_provider_state import ReaProviderStore


class StdioMcpBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_managed_rea_keeps_one_process_for_stateful_tool_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "stateful_mcp_server.py"
            script.write_text(textwrap.dedent("""
                import json
                import sys

                target_open = False
                for line in sys.stdin:
                    request = json.loads(line)
                    method = request.get("method")
                    if method == "initialize":
                        result = {"serverInfo": {"name": "rea", "version": "6.9.0"}}
                    elif method == "tools/call":
                        name = request["params"]["name"]
                        if name == "open_binary":
                            target_open = True
                            result = {"structuredContent": {"result": {"open": True}}}
                        else:
                            result = {"structuredContent": {"result": {"open": target_open}}}
                    else:
                        continue
                    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
            """), encoding="utf-8")
            provider = root / "provider"
            store = ReaProviderStore(provider / "state.sqlite")
            candidate = store.discover("6.9.0", integrity="sha512-x", source="https://registry.npmjs.org")
            for state in ("acquiring", "staged", "verifying", "ready"):
                candidate = store.transition(candidate.version, state, expected_revision=candidate.revision)
            store.activate("6.9.0", expected_generation=0)
            store.close()
            config = McpServerConfig(
                name="rea",
                command=sys.executable,
                args=(str(script),),
                allowed_tools=frozenset({"*"}),
            )
            backend = LeasedReaBackend(provider, config)

            with patch("web_app.core.mcp_stdio_backend._versioned_rea_config", return_value=config):
                try:
                    await backend.invoke("open_binary", {"path": "D:/target.exe"})
                    status = await backend.invoke("binary_session", {})
                finally:
                    await backend.close()

            self.assertTrue(status["structuredContent"]["result"]["open"])

    async def test_reads_large_real_world_tool_catalog_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "large_mcp_server.py"
            script.write_text(textwrap.dedent("""
                import json
                import sys

                for line in sys.stdin:
                    request = json.loads(line)
                    if request.get("method") == "initialize":
                        result = {"serverInfo": {"name": "large", "version": "1.0.0"}}
                    elif request.get("method") == "tools/list":
                        result = {"tools": [{"name": "inspect", "description": "x" * 70000, "inputSchema": {"type": "object"}}]}
                    else:
                        continue
                    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
            """), encoding="utf-8")
            backend = StdioMcpBackend(McpServerConfig(
                name="large",
                command=sys.executable,
                args=(str(script),),
                allowed_tools=frozenset({"inspect"}),
                tool_timeout_seconds=1,
            ))
            self.addAsyncCleanup(backend.close)

            discovered = await backend.discover()

            self.assertEqual(len(discovered["tools"][0]["description"]), 70000)

    async def test_negotiates_lists_and_calls_tools_over_real_stdio(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "fake_mcp_server.py"
            script.write_text(textwrap.dedent("""
                import json
                import sys

                for line in sys.stdin:
                    request = json.loads(line)
                    method = request.get("method")
                    if method == "initialize":
                        result = {
                            "protocolVersion": request["params"]["protocolVersion"],
                            "capabilities": {"tools": {"listChanged": False}},
                            "serverInfo": {"name": "fixture", "version": "1.0.0"},
                        }
                    elif method == "tools/list":
                        result = {
                            "tools": [{
                                "name": "inspect",
                                "description": "Inspect one target",
                                "inputSchema": {"type": "object"},
                            }]
                        }
                    elif method == "tools/call":
                        result = {
                            "content": [{"type": "text", "text": request["params"]["arguments"]["path"]}],
                            "structuredContent": {"evidence_id": "evidence:real-1"},
                            "isError": False,
                        }
                    else:
                        continue
                    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
            """), encoding="utf-8")
            backend = StdioMcpBackend(McpServerConfig(
                name="fixture",
                command=sys.executable,
                args=(str(script),),
                allowed_tools=frozenset({"inspect"}),
            ))
            self.addAsyncCleanup(backend.close)

            discovered = await backend.discover()
            invoked = await backend.invoke("inspect", {"path": "D:/target.exe"})

            self.assertEqual(discovered["server"]["name"], "fixture")
            self.assertEqual(discovered["tools"][0]["name"], "inspect")
            self.assertEqual(invoked["structuredContent"]["evidence_id"], "evidence:real-1")
            self.assertFalse(invoked["isError"])

    def test_loads_explicit_manual_server_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp_servers.json"
            path.write_text(json.dumps({
                "mcpServers": {
                    "rea": {
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["D:/tools/rea.mjs", "mcp"],
                        "env": {"GHIDRA_INSTALL_DIR": "D:/tools/ghidra"},
                        "allowedTools": ["*"],
                    }
                }
            }), encoding="utf-8")

            configs = load_mcp_server_configs(path)

            self.assertEqual(configs[0].name, "rea")
            self.assertEqual(configs[0].transport, "stdio")
            self.assertEqual(configs[0].args[-1], "mcp")
            self.assertEqual(configs[0].env["GHIDRA_INSTALL_DIR"], "D:/tools/ghidra")
            self.assertEqual(configs[0].allowed_tools, frozenset({"*"}))

            adapters, backends = build_mcp_adapters(path)

            self.assertEqual(set(adapters), {"mcp.rea"})
            self.assertEqual(backends[0].config.name, "rea")

    def test_active_rea_provider_overrides_only_the_manual_rea_launch_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "mcp_servers.json"
            config_path.write_text(json.dumps({"mcpServers": {"rea": {
                "command": "global-node.exe", "args": ["global-rea.mjs", "mcp"],
                "env": {"JAVA_HOME": "D:/jdk"}, "allowedTools": ["*"]
            }}}), encoding="utf-8")
            provider = root / "providers" / "rea"
            script = provider / "versions" / "6.9.0" / "installation" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
            script.parent.mkdir(parents=True)
            script.write_text("// real", encoding="utf-8")
            (provider / "active.json").write_text(json.dumps({"generation": 1, "version": "6.9.0"}), encoding="utf-8")

            _, backends = build_mcp_adapters(config_path, rea_provider_root=provider)

            self.assertEqual(Path(backends[0].config.command), Path(shutil.which("node")))
            self.assertEqual(Path(backends[0].config.args[0]), script)
            self.assertEqual(backends[0].config.env["JAVA_HOME"], "D:/jdk")

    def test_managed_rea_is_registered_without_manual_mcp_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "mcp_servers.json"
            provider = root / "providers" / "rea"
            store = ReaProviderStore(provider / "state.sqlite")
            candidate = store.discover("6.9.0", integrity="sha512-x", source="https://registry.npmjs.org")
            for state in ("acquiring", "staged", "verifying", "ready"):
                candidate = store.transition(candidate.version, state, expected_revision=candidate.revision)
            store.activate("6.9.0", expected_generation=0)
            store.close()

            adapters, backends = build_mcp_adapters(config_path, rea_provider_root=provider)

            self.assertEqual(set(adapters), {"mcp.rea"})
            self.assertIsInstance(backends[0], LeasedReaBackend)
            self.assertIsNone(backends[0]._backend)

    def test_active_craft_component_registers_clean_room_and_deep_mcp_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            command = ("D:/components/craft-anything-cli.exe",)

            adapters, backends = build_mcp_adapters(
                Path(directory) / "mcp_servers.json", craft_command=command,
            )

            self.assertEqual(set(adapters), {"mcp.craft-clean-room", "mcp.craft-deep"})
            configs = {backend.config.name: backend.config for backend in backends}
            self.assertEqual(configs["craft-clean-room"].command, command[0])
            self.assertEqual(configs["craft-clean-room"].args, ("--clean-room", "mcp"))
            self.assertEqual(configs["craft-deep"].args, ("--deep", "mcp"))
            self.assertEqual(configs["craft-deep"].allowed_tools, frozenset({"*"}))

    async def test_rejects_repeated_pagination_cursor(self):
        backend = StdioMcpBackend(McpServerConfig(name="loop", command="unused"))

        async def started():
            return None

        async def request(method, params, timeout):
            return {"tools": [], "nextCursor": "same"}

        backend._ensure_started = started
        backend._request = request

        with self.assertRaisesRegex(RuntimeError, "repeated"):
            await backend.discover()


if __name__ == "__main__":
    unittest.main()
