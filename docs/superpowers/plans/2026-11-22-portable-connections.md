# Portable Connections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Settings > Connections surface and portable JSON_CODR discovery/bootstrap that works after relocation or installation on another computer.

**Architecture:** Extend the existing ConnectionRecoveryService with concrete program adapters and a portable installation resolver. Keep fixed HTTP as the normal path, add Streamable HTTP MCP beside stdio, and route every UI mutation through typed service endpoints.

**Tech Stack:** Python 3.15, FastAPI, Pydantic, PowerShell, vanilla JavaScript/HTML/CSS, unittest

**Spec:** `docs/superpowers/specs/2026-11-22-portable-connections-design.md`

## Global Constraints

- Reuse existing Settings UI components and interaction behavior exactly.
- Keep existing Ollama, stdio MCP, plugin, and direct model selection functional.
- Never perform unrestricted disk scans or persist plaintext credentials.
- Scans are read-only; writes require preview, approval, backup, and reversal.
- A connector is ready only after a real functional probe.

## Review Focus

- A stale manifest must degrade cleanly and offer repair rather than start the wrong checkout.
- A healthy unrelated process on port 8765 must not be accepted as JSON_CODR.
- Remote/container clients must not inherit unusable local paths.
- Malformed third-party configuration must not be overwritten or leak secrets in diagnostics.
- Narrow Settings widths must wrap controls without hiding reverse actions.

---

### Task 1: Portable installation resolver and bootstrap

**Files:**
- Create: `web_app/integrations/installation.py`
- Create: `scripts/register_installation.py`
- Modify: `integrations/vscode-json-codr/start_mcp.ps1`
- Test: `test_ide_agent_bridge.py`

**Interfaces:**
- Produces: `InstallationResolver.resolve(explicit_root: str | None) -> InstallationResolution`
- Produces: `register_installation(root: Path, service_url: str) -> InstallationManifest`

- [ ] Write failing tests for explicit, environment, manifest, plugin-relative, stale-manifest, moved-root, and wrong-service-on-port resolution.
- [ ] Run the focused resolver tests and confirm failures are caused by missing resolver behavior.
- [ ] Implement the resolver, atomic per-user manifest registration, and bootstrap integration.
- [ ] Run resolver and existing IDE bridge tests; expect all to pass.
- [ ] Review the diff before continuing.

### Task 2: Fixed HTTP and Streamable HTTP MCP transport

**Files:**
- Create: `web_app/integrations/mcp_http.py`
- Modify: `web_app/app.py`
- Modify: `web_app/integrations/mcp_server.py`
- Test: `test_mcp_stdio_backend.py`
- Test: `test_ide_agent_bridge.py`

**Interfaces:**
- Consumes: existing `BorgClient` tool implementations.
- Produces: `/mcp` Streamable HTTP endpoint with the same bounded tool catalog as stdio.

- [ ] Write failing transport-parity tests for initialization, tool listing, health, models, invalid sessions, and unavailable service behavior.
- [ ] Run the focused tests and verify expected failures.
- [ ] Implement HTTP transport by sharing tool dispatch with stdio rather than duplicating handlers.
- [ ] Run HTTP and stdio transport tests; expect parity and all passes.
- [ ] Review the diff before continuing.

### Task 3: Program discovery and recovery adapters

**Files:**
- Create: `web_app/integrations/connection_adapters.py`
- Modify: `web_app/core/connection_recovery.py`
- Modify: `web_app/models.py`
- Modify: `web_app/app.py`
- Test: `test_connection_recovery.py`
- Test: `test_provider_compatibility.py`

**Interfaces:**
- Produces: inventory, scan, preview, configure, test, repair, disable, remove, and restore endpoints.
- Supports: VS Code/Copilot, Visual Studio, Codex, Claude, Cursor, Windsurf, Ollama, generic MCP, and generic OpenAI-compatible clients.

- [ ] Write failing adapter tests for bounded discovery, malformed configurations, sanitized diagnostics, backup/restore, and truthful readiness.
- [ ] Run focused tests and verify failures.
- [ ] Implement concrete adapters and thin API routes over ConnectionRecoveryService.
- [ ] Run recovery and provider compatibility tests; expect all passes.
- [ ] Review the diff before continuing.

### Task 4: Settings > Connections interface

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Modify: `test_web_static.py`
- Modify: `test_settings.py`

**Interfaces:**
- Consumes: Task 3 typed connection APIs.
- Produces: Overview, Programs, JSON_CODR Service, and Advanced Settings disclosures.

- [ ] Write failing static and settings-state tests for submenu presence, collapsed unavailable connectors, status semantics, reverse actions, keyboard access, and responsive wrapping.
- [ ] Run focused web tests and verify failures.
- [ ] Implement the submenu using existing Settings classes, controls, tokens, and rendering patterns.
- [ ] Run focused web/settings tests and expect all passes.
- [ ] Verify light/dark themes and narrow/wide layouts in the live browser with before/after captures.

### Task 5: Portable configuration generation and final verification

**Files:**
- Create: `web_app/integrations/configuration_export.py`
- Modify: `integrations/generic/adapter-manifest.json`
- Modify: `integrations/visual-studio-2022/.mcp.json`
- Modify: `integrations/vscode-json-codr/mcp.json`
- Modify: `README.md`
- Test: `test_ide_agent_bridge.py`
- Test: `test_deployment.py`

**Interfaces:**
- Produces: per-program configuration previews and portable export/import bundles without credentials.

- [ ] Write failing tests for generated native formats, relocation, remote-host warnings, secret exclusion, and round-trip import.
- [ ] Run focused tests and verify failures.
- [ ] Implement generation/export and concise setup/recovery guidance.
- [ ] Run all connector, recovery, settings, deployment, and unchanged legacy integration tests.
- [ ] Run Python compilation, PowerShell parsing, JSON/JSONC validation, lint, and `git diff --check`.
- [ ] Perform one real cold-start, one relocated-copy probe, and one live UI verification without using mock responses.
