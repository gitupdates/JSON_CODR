from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from web_app.core.mcp_stdio_backend import McpServerConfig, StdioMcpBackend
from web_app.core.rea_provider_state import ReaProviderStore


@dataclass(frozen=True)
class ReaProbePolicy:
    required_tools: frozenset[str]
    harmless_tool: str
    harmless_arguments: dict | None = None


@dataclass(frozen=True)
class ReaProbeEvidence:
    version: str
    server_version: str
    server_name: str
    tool_count: int
    catalog_digest: str
    harmless_tool: str
    harmless_result_digest: str


class ReaCandidateVerifier:
    def __init__(
        self,
        root: str | Path,
        store: ReaProviderStore,
        backend_factory=StdioMcpBackend,
        policy: ReaProbePolicy | None = None,
        *,
        node_path: str = "node.exe",
        environment: dict[str, str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.store = store
        self.backend_factory = backend_factory
        self.policy = policy or ReaProbePolicy(frozenset(), "")
        self.node_path = node_path
        self.environment = dict(environment or {})

    async def verify(self, version: str) -> ReaProbeEvidence:
        candidate = self.store.candidate(version)
        was_active = candidate.state == "active"
        if candidate.state not in {"staged", "quarantined", "active"}:
            raise ValueError(f"REA {version} is not staged for verification")
        if not was_active:
            candidate = self.store.transition(version, "verifying", expected_revision=candidate.revision)
        version_root = (self.root / "versions" / version).resolve()
        script = version_root / "installation" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
        package_path = script.parent.parent / "package.json"
        backend = None
        try:
            version_root.relative_to((self.root / "versions").resolve())
            if not script.is_file() or not package_path.is_file():
                raise RuntimeError("REA candidate launch files are missing")
            package = json.loads(package_path.read_text(encoding="utf-8"))
            if package.get("name") != "rea-agents" or package.get("version") != version:
                raise RuntimeError("REA candidate package identity mismatch")
            config = McpServerConfig(
                name="rea",
                command=self.node_path,
                args=(str(script), "mcp"),
                env=self.environment,
                allowed_tools=frozenset({"*"}),
            )
            backend = self.backend_factory(config)
            discovery = await backend.discover()
            server = discovery.get("server", {})
            server_version = str(server.get("version", ""))
            if server_version != version:
                raise RuntimeError(f"REA server version mismatch: expected {version}, got {server_version or 'missing'}")
            tools = discovery.get("tools", [])
            names = []
            normalized = []
            for tool in tools:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                    raise RuntimeError("REA returned an invalid tool entry")
                schema = tool.get("inputSchema")
                if not isinstance(schema, dict):
                    raise RuntimeError(f"REA tool {tool['name']} has no valid input schema")
                self._validate_schema(schema, tool["name"])
                names.append(tool["name"])
                normalized.append({"name": tool["name"], "inputSchema": schema})
            if len(names) != len(set(names)):
                raise RuntimeError("REA returned duplicate tool names")
            missing = self.policy.required_tools.difference(names)
            if missing:
                raise RuntimeError(f"REA candidate is missing required tools: {', '.join(sorted(missing))}")
            if not self.policy.harmless_tool or self.policy.harmless_tool not in names:
                raise RuntimeError("REA harmless probe tool is unavailable")
            result = await backend.invoke(self.policy.harmless_tool, self.policy.harmless_arguments or {})
            if not isinstance(result, dict) or not result or result.get("isError") is True:
                raise RuntimeError("REA harmless probe returned no structured result")
            if str(server.get("name", "")).lower() != "rea":
                raise RuntimeError("MCP server did not identify itself as REA")
            await backend.close()
            backend = self.backend_factory(config)
            restart = await backend.discover()
            restart_server = restart.get("server", {})
            if restart_server.get("name", "").lower() != "rea" or restart_server.get("version") != version:
                raise RuntimeError("REA candidate failed the clean restart identity probe")
            restart_names = {tool.get("name") for tool in restart.get("tools", []) if isinstance(tool, dict)}
            if set(names) != restart_names:
                raise RuntimeError("REA tool catalog changed after a clean restart")
            catalog_json = json.dumps(sorted(normalized, key=lambda item: item["name"]), sort_keys=True, separators=(",", ":"))
            result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
            evidence = ReaProbeEvidence(
                version=version,
                server_version=server_version,
                server_name=str(server.get("name", "rea")),
                tool_count=len(tools),
                catalog_digest="sha256:" + hashlib.sha256(catalog_json.encode()).hexdigest(),
                harmless_tool=self.policy.harmless_tool,
                harmless_result_digest="sha256:" + hashlib.sha256(result_json.encode()).hexdigest(),
            )
            skill_source = package_path.parent / "skills" / "reverse-engineer-anything"
            if not (skill_source / "SKILL.md").is_file():
                raise RuntimeError("REA bundled skill is missing")
            skill_target = version_root / "skill"
            if skill_target.exists():
                shutil.rmtree(skill_target)
            shutil.copytree(skill_source, skill_target)
            (version_root / "probe-evidence.json").write_text(
                json.dumps(asdict(evidence), indent=2, sort_keys=True), encoding="utf-8"
            )
            if not was_active:
                self.store.transition(version, "ready", expected_revision=candidate.revision)
            return evidence
        except BaseException:
            current = self.store.candidate(version)
            if current.state == "verifying":
                self.store.transition(version, "quarantined", expected_revision=current.revision)
            raise
        finally:
            if backend is not None:
                await backend.close()

    @staticmethod
    def _validate_schema(schema: dict, tool_name: str) -> None:
        allowed_types = {"array", "boolean", "integer", "null", "number", "object", "string"}
        schema_type = schema.get("type")
        if schema_type is not None and not (
            isinstance(schema_type, str) and schema_type in allowed_types
            or isinstance(schema_type, list) and schema_type and all(item in allowed_types for item in schema_type)
        ):
            raise RuntimeError(f"REA tool {tool_name} has an invalid JSON Schema type")
        properties = schema.get("properties")
        if properties is not None and not isinstance(properties, dict):
            raise RuntimeError(f"REA tool {tool_name} has invalid JSON Schema properties")
        required = schema.get("required")
        if required is not None and not (
            isinstance(required, list) and all(isinstance(item, str) for item in required)
        ):
            raise RuntimeError(f"REA tool {tool_name} has invalid JSON Schema required fields")
        if isinstance(properties, dict):
            for name, child in properties.items():
                if not isinstance(name, str) or not isinstance(child, dict):
                    raise RuntimeError(f"REA tool {tool_name} has an invalid property schema")
                ReaCandidateVerifier._validate_schema(child, tool_name)
