# JSON_CODR for Visual Studio 2022

This adapter connects GitHub Copilot Agent mode in Visual Studio 2022 17.14 or later to the running JSON_CODR BORG service.

1. Start JSON_CODR and verify `http://127.0.0.1:8874/api/health` reports ready.
2. Ensure the Python environment used by Visual Studio can import this JSON_CODR checkout.
3. Copy `.mcp.json` to the solution root or merge its `json-codr-borg` entry into `%USERPROFILE%\.mcp.json`.
4. Open Copilot Chat, choose Agent mode, open Tools, and enable the JSON_CODR tools.
5. Ask Copilot to call `json_codr.health` before submitting a workspace task.

Visual Studio still applies its MCP trust and tool-approval controls. BORG independently enforces JSON_CODR project boundaries and approval state.
