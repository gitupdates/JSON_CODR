# Portable Connections Design

## Intent

JSON_CODR must connect to supported local programs through one understandable Settings surface and continue working after its repository is moved or installed on another computer.

## Goals

- Add Settings > Connections using the existing Settings visual language and interaction patterns.
- Preserve native program integrations while offering fixed local HTTP, Streamable HTTP MCP, stable stdio bootstrap, remote HTTP, and plugin-managed methods where supported.
- Discover installed programs and configurations through bounded, read-only probes.
- Register and repair a relocated JSON_CODR installation without embedding repository paths in portable configuration.
- Verify health, tools, and models before reporting a connection ready.

## Non-goals

- Do not scan entire drives.
- Do not copy credentials between programs or store plaintext secrets in connector manifests.
- Do not replace existing Ollama or stdio integrations.
- Do not introduce a second task or approval authority outside BORG and ConnectionRecoveryService.

## Constraints

- Existing Settings components, theme tokens, spacing, typography, disclosure controls, button variants, responsive wrapping, keyboard behavior, loading states, and error states remain authoritative.
- Scanning is read-only. Configuration writes require a preview and timestamped backup.
- Disabled or unavailable connectors stay collapsed outside the primary flow.
- Every action has a reverse action and a visible status.
- Per-user configuration is separate from project configuration.

## Selected approach

Use a fixed local HTTP endpoint as the normal connection path and a stable per-user bootstrap as the relocation and cold-start path. The bootstrap resolves an explicit root, `JSON_CODR_ROOT`, a per-user installation manifest, a plugin-relative root, then narrowly scoped known locations. Every candidate must pass launcher and application validation.

Settings > Connections contains Overview, Programs, JSON_CODR Service, and Advanced disclosures. Installed and active programs appear first. Unavailable connectors remain collapsed. Program cards expose configure, test, repair, disable, remove, and configuration-preview operations using ConnectionRecoveryService adapters.

## Alternatives considered

- Environment variable only: small, but fragile across GUI launches, remote hosts, and new computers.
- Fixed HTTP only: simple after startup, but unable to locate or start a moved installation.
- Stable bootstrap plus HTTP: selected because it keeps the common path simple while providing deterministic recovery.

## Verification

Tests cover relocated roots, stale manifests, unavailable runtimes, port conflicts, malformed external configuration, backup and reversal, truthful readiness, responsive Settings layout, and unchanged legacy stdio/Ollama behavior.
