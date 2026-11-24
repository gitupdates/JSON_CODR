# IDE Agent Adapters Design

## Goal

Expose JSON_CODR as an agent capability in VS Code with GitHub Copilot, Visual Studio 2022, and future MCP-compatible clients without duplicating BORG behavior in editor-specific integrations.

## Architecture

One outward-facing MCP bridge translates MCP discovery and tool calls into JSON_CODR HTTP API requests. The bridge is a transport adapter only: BORG remains responsible for project boundaries, model routing, approvals, execution, evidence, and audit records.

The initial tool surface is intentionally small:

- `json_codr.health` verifies the live service and version.
- `json_codr.models` returns the installed model roster.
- `json_codr.run_workspace_task` submits work through `/api/workspace/tasks`.

The bridge supports stdio for local IDEs. Its protocol-facing code is separated from the HTTP client so a future Streamable HTTP host can reuse the same contracts.

## Adapter Packages

### VS Code with GitHub Copilot

An agent plugin bundles a custom `JSON_CODR` agent, the MCP launch configuration, and a focused skill. VS Code supplies editor-native tools; JSON_CODR supplies BORG operations through MCP.

### Visual Studio 2022

A solution/user `.mcp.json` template launches the same bridge. Visual Studio 2022 17.14 uses the tools from Copilot Agent mode. Instructions explain the BORG boundary and verification expectations without claiming unsupported custom-agent behavior.

### Generic Clients

A versioned manifest and JSON Schema describe the bridge command, supported transports, protocol version, tools, and optional client capabilities. Unknown clients can negotiate from this manifest rather than depending on editor-specific files.

## Safety and Compatibility

- IDE adapters never manipulate files, Git, terminals, REA, or Ghidra directly.
- Workspace tasks require an existing JSON_CODR session and a project root.
- HTTP failures become MCP errors with bounded, non-secret messages.
- Tool schemas reject unknown fields and malformed paths before contacting BORG.
- Existing inbound MCP support remains unchanged.
- The existing `.vscode/launch.json` is user-owned and is not modified.

## Verification

Focused tests exercise MCP initialization, tool discovery, health and model calls, workspace submission, API error mapping, malformed requests, and static adapter manifests. A real stdio smoke test launches the bridge against a temporary local HTTP fixture.
