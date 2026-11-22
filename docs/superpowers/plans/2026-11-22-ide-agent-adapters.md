# IDE Agent Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make JSON_CODR available as an agent capability in VS Code with GitHub Copilot, Visual Studio 2022, and generic future MCP clients.

**Architecture:** A small stdio MCP bridge calls existing JSON_CODR HTTP endpoints and never reimplements BORG operations. Editor-specific packages contain only manifests, instructions, and launch configuration; a generic manifest/schema documents the stable compatibility boundary.

**Tech Stack:** Python 3.12+, JSON-RPC/MCP over stdio, urllib HTTP client, JSON Schema, VS Code agent plugins, Visual Studio `.mcp.json`.

**Spec:** `docs/superpowers/specs/2026-11-22-ide-agent-adapters-design.md`

## Global Constraints

- BORG remains the only authority for project execution, permissions, evidence, and audit history.
- Do not modify the user-owned `.vscode/launch.json`.
- Do not add third-party runtime dependencies.
- Preserve existing inbound MCP client behavior.
- All new protocol responses use real JSON_CODR service data.

## Review Focus

- A stopped JSON_CODR server returns an MCP error without crashing the bridge.
- Malformed JSON-RPC input is rejected while the process remains available for the next request.
- Unknown tools and unknown tool arguments are rejected before an HTTP call.
- Workspace task responses preserve approval-required and asynchronous states.
- Windows paths and command arguments remain valid in all three adapter manifests.

---

### Task 1: BORG HTTP client

**Files:**
- Create: `web_app/integrations/borg_client.py`
- Test: `test_ide_agent_bridge.py`

**Interfaces:**
- Produces: `BorgClient(base_url: str, timeout_seconds: float = 30.0)` with `health()`, `models()`, and `run_workspace_task(...)`.

- [ ] Write focused tests using a real temporary HTTP fixture for successful requests, API errors, and unreachable service behavior.
- [ ] Run `python -m unittest test_ide_agent_bridge.BorgClientTests -v` and verify expected failures because the client is absent.
- [ ] Implement the minimal standard-library HTTP client and bounded error mapping.
- [ ] Run the focused tests and verify they pass.

### Task 2: Stdio MCP bridge

**Files:**
- Create: `web_app/integrations/mcp_server.py`
- Create: `web_app/integrations/__init__.py`
- Extend: `test_ide_agent_bridge.py`

**Interfaces:**
- Consumes: `BorgClient` from Task 1.
- Produces: `McpServer(client: BorgClient)` and `main(argv: list[str] | None = None) -> int`.

- [ ] Add failing protocol tests for initialize, tools/list, each tool call, malformed requests, unknown tools, and unknown arguments.
- [ ] Run `python -m unittest test_ide_agent_bridge.McpServerTests -v` and verify failures because the server is absent.
- [ ] Implement newline-delimited JSON-RPC 2.0 with MCP protocol `2025-06-18` and the three bounded tools.
- [ ] Run the focused tests and verify they pass.

### Task 3: IDE and generic adapter packages

**Files:**
- Create: `integrations/vscode-json-codr/plugin.json`
- Create: `integrations/vscode-json-codr/mcp.json`
- Create: `integrations/vscode-json-codr/com.github.copilot/agents/json-codr.agent.md`
- Create: `integrations/vscode-json-codr/skills/json-codr-workspace/SKILL.md`
- Create: `integrations/visual-studio-2022/.mcp.json`
- Create: `integrations/visual-studio-2022/README.md`
- Create: `integrations/generic/adapter-manifest.json`
- Create: `integrations/generic/adapter-manifest.schema.json`
- Extend: `test_ide_agent_bridge.py`

**Interfaces:**
- Consumes: `python -m web_app.integrations.mcp_server` from Task 2.
- Produces: installable VS Code plugin source, Visual Studio MCP template, and generic adapter contract.

- [ ] Add failing static contract tests for required files, valid JSON, manifest/schema consistency, Windows-safe launch arguments, and agent/skill metadata.
- [ ] Run `python -m unittest test_ide_agent_bridge.AdapterPackageTests -v` and verify failures because packages are absent.
- [ ] Add the minimal package files without editor-specific execution logic.
- [ ] Run the focused tests and verify they pass.

### Task 4: Integrated verification

**Files:**
- Modify only if verification exposes a defect in the files above.

**Interfaces:**
- Consumes: all Task 1-3 outputs.
- Produces: verified bridge and adapter packages.

- [ ] Run `python -m unittest test_ide_agent_bridge test_mcp_stdio_backend -v`.
- [ ] Run the repository's targeted architecture and web API tests affected by the new module.
- [ ] Start the MCP bridge against the live V1.3.2 service and verify `initialize`, `tools/list`, and `json_codr.health` return real service data.
- [ ] Review `git diff --check` and `git status --short`, confirming `.vscode/launch.json` remains untouched.
