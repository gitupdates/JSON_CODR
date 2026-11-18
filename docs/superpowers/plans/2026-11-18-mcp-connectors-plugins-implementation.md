# MCP, Connectors, Skills, and Plugins V1.0.18-alpha.13 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task-by-task after alpha.12 is complete. Use `superpowers:test-driven-development` for every behavior change and `superpowers:verification-before-completion` before release.

**Goal:** Add a provider-neutral plugin platform and open MCP connector client with secure transports, authorization, contribution management, and policy integration.

**Architecture:** Extend the existing component acquisition/quarantine/runtime pipeline with a strict plugin manifest and contribution registry. Keep skills, Skillsets, connectors, commands, and agent profiles as distinct domain objects. Add transport-neutral MCP sessions and an OS-protected authorization broker, then integrate every contribution with alpha.12 plan digests and policy gates.

**Tech stack:** Python 3.12, Pydantic, SQLite, FastAPI, vanilla JavaScript/CSS, Windows Credential Manager/DPAPI abstraction, MCP JSON-RPC, OAuth 2.1/PKCE, `unittest`.

---

## Task 1: Define and validate the plugin manifest

**Files:** Create `web_app/core/plugin_manifest.py`, `docs/user/json-codr-plugin.schema.json`, `test_plugin_manifest.py`; modify `web_app/core/component_inspection.py`.

1. Write failing tests for valid manifests, unknown keys, traversal, symlink escape, hash/size mismatch, secret-bearing connector definitions, contribution collisions, incompatible versions, and malicious archives.
2. Run `python -m unittest test_plugin_manifest.py -v` and confirm failure.
3. Implement strict Pydantic contracts, content-manifest verification, and passive-asset restrictions.
4. Re-run the test and commit with `feat(plugins): define verified plugin manifest`.

## Task 2: Add contribution registry and immutable installation

**Files:** Create `web_app/core/plugin_registry.py`, `test_plugin_registry.py`; modify `component_acquisition.py`, `component_registry.py`, `component_runtime.py`, and their tests.

1. Write failing tests for preview, exact-digest approval, quarantine, atomic install, partial enablement, local/project/user scope, update diff, rollback, uninstall tombstones, and crash recovery.
2. Implement immutable version directories and separately registered contributions using the existing component lifecycle.
3. Run `python -m unittest test_plugin_registry.py test_component_acquisition.py test_component_registry.py test_component_runtime.py -v`.
4. Commit with `feat(plugins): install immutable contribution bundles`.

## Task 3: Register skills, Skillsets, commands, and agent profiles

**Files:** Create `web_app/core/plugin_contributions.py`, `test_plugin_contributions.py`; modify `web_app/skills.py`, `web_app/skillsets.py`, `web_app/recommendations.py`, and `web_app/coding_agents.py`.

1. Write failing tests proving skills remain lazy/provider-neutral, Skillsets remain references, slash commands expand only to task/plan input, and agent profiles cannot broaden capabilities or policy.
2. Implement contribution adapters with origin digests and independent enablement.
3. Run `python -m unittest test_plugin_contributions.py test_skills.py test_skillsets.py test_recommendations.py test_coding_agents.py -v`.
4. Commit with `feat(plugins): register constrained plugin contributions`.

## Task 4: Extract a transport-neutral MCP client

**Files:** Create `web_app/core/mcp_client.py`, `web_app/core/mcp_transport.py`, `test_mcp_client.py`; modify `mcp_stdio_backend.py`, `mcp_adapter.py`, and `test_mcp_stdio_backend.py`.

1. Write failing lifecycle/capability/version/pagination/cancellation tests that pass through a transport interface.
2. Move current stdio behavior behind `StdioMcpTransport` without changing existing behavior.
3. Run `python -m unittest test_mcp_client.py test_mcp_stdio_backend.py test_mcp_plan_safety.py -v`.
4. Commit with `refactor(mcp): add transport-neutral client`.

## Task 5: Add hardened Streamable HTTP transport

**Files:** Create `web_app/core/mcp_http_transport.py`, `test_mcp_http_transport.py`; modify `web_app/core/mcp_client.py`.

1. Write failing mock-server tests for POST/GET streaming, content types, protocol versions, redirects, TLS policy, DNS/private-address rules, Origin behavior, session lifecycle, response limits, malformed JSON-RPC, reconnect, and explicit legacy SSE compatibility.
2. Implement Streamable HTTP with bounded I/O and cancellation.
3. Run `python -m unittest test_mcp_http_transport.py test_mcp_client.py -v`.
4. Commit with `feat(mcp): add hardened streamable HTTP transport`.

## Task 6: Add OAuth broker and protected credential storage

**Files:** Create `web_app/core/mcp_auth.py`, `web_app/core/credential_store.py`, `test_mcp_auth.py`, `test_credential_store.py`; modify `mcp_http_transport.py`.

1. Write failing tests for protected-resource discovery, authorization-server metadata, PKCE, state, callback binding, dynamic/static client registration, resource indicators, audience validation, refresh, revoke, scope escalation, redirect attacks, token passthrough, and redaction.
2. Implement an injectable credential-store interface and Windows protected implementation; persist only opaque references.
3. Run `python -m unittest test_mcp_auth.py test_credential_store.py test_mcp_http_transport.py -v`.
4. Commit with `feat(connectors): add secure OAuth authorization`.

## Task 7: Implement complete MCP feature providers

**Files:** Create `web_app/core/mcp_resources.py`, `mcp_prompts.py`, `mcp_elicitation.py`, `mcp_tasks.py`, and corresponding tests; modify `mcp_client.py` and `mcp_adapter.py`.

1. Write failing tests for tools, resources, templates, prompts, completions, elicitation form/URL modes, notifications, subscriptions, pagination, long-running tasks, cancellation, schema drift, tool deferral, output bounds, and uncertain-effect recovery.
2. Implement each provider behind negotiated capabilities and alpha.12 provenance/policy contracts.
3. Run all `test_mcp_*.py` tests.
4. Commit with `feat(mcp): support resources prompts and elicitation`.

## Task 8: Expose connector and plugin APIs

**Files:** Create `web_app/core/plugin_api.py`, `web_app/core/connector_api.py`, `test_plugin_api.py`, `test_connector_api.py`; modify `web_app/app.py`, `web_app/models.py`, and `web_app/core/api.py`.

1. Write failing tests for preview/install/enable/update/rollback/uninstall, connector add/connect/status/reconnect/revoke, scope and tool-policy changes, optimistic digests, and RFC 9457 redacted errors.
2. Implement APIs as thin adapters over registries and brokers; never return credentials.
3. Run `python -m unittest test_plugin_api.py test_connector_api.py test_core_api.py test_web_api.py -v`.
4. Commit with `feat(api): expose plugin and connector lifecycle`.

## Task 9: Build Skills & Plugins and Connectors UI

**Files:** Create `web/plugins.js`, `web/connectors.js`, `test_plugins_ui.py`, `test_connectors_ui.py`; modify `web/index.html`, `web/app.js`, `web/app.css`, `web/gamma.css`, `web/ui_catalog.js`.

1. Write failing tests for Skills/Skillsets/Plugins/Connectors tabs, contribution preview, independent install-enable-connect-permit actions, provenance/license/version, status/diagnostics, account/scopes, per-tool policy, update diff, rollback, keyboard/focus, narrow screens, and secret absence.
2. Implement host-rendered UI using the neutral heading “Skills & plugins: teach JSON_CODR your way.”
3. Run `python -m unittest test_plugins_ui.py test_connectors_ui.py test_web_static.py test_ui_customization.py -v`.
4. Commit with `feat(ui): add skills plugins and connectors management`.

## Task 10: End-to-end security, compatibility, and release

**Files:** Create `test_plugin_connector_e2e.py`, `test_plugin_connector_security.py`; modify `README.md`, `docs/user/json-codr-skill-envelope.md`, `docs/user/provider-compatibility.md`, `web_app/version.py`, `test_version.py`.

1. Test install-to-plan provenance, OAuth-to-resource-read, guarded external write, schema/scope invalidation, offline recovery, rollback, uninstall tombstones, stdio compatibility, and malicious plugin/MCP scenarios.
2. Set `V1.0.18-alpha.13` and document formats, trust boundaries, scopes, credential storage, and limitations.
3. Run `python -m unittest discover -v`, `python -m compileall -q web_app`, and `git diff --check`.
4. Perform Windows local smoke tests for stdio and mock Streamable HTTP/OAuth connectors.
5. Request independent code review and complete the verification/branch-finishing skills before publication.
