# Automatic prerequisite installation design

## Intent

When JSON_CODR detects Python or Node prerequisites in an imported manifest, it should identify packages that are missing or incompatible and install only those packages through the running live CLI. Installation output remains visible so the user can monitor or stop it.

## Goals

- Inspect validated entries from `requirements.txt`, `requirements-dev.txt`, and `package.json`.
- Compare requested Python packages and versions with the active Python environment.
- Compare requested Node packages and versions with the active workspace installation.
- Automatically open the live CLI and run a bounded install command containing only missing or incompatible packages.
- Stream normal package-manager output through the existing terminal panel.
- Avoid launching the same install more than once per page session while it is already queued or running.

## Non-goals

- Installing operating-system packages, drivers, services, or tools requiring administrator elevation.
- Executing lifecycle commands copied from manifests.
- Running arbitrary shell strings supplied by model output or attachment text.
- Silently changing packages that already satisfy the requested version range.

## Selected approach

This combines the two requested approaches:

1. The dependency service parses and validates manifest entries as it does today.
2. A preflight layer checks each validated requirement without invoking a shell:
   - Python uses installed distribution metadata and PEP 440 requirement matching.
   - Node uses bounded `npm ls <package@range> --depth=0 --json` subprocess calls with argument arrays and no shell expansion.
3. The API returns suggestions containing only missing or incompatible dependencies and marks them for automatic installation.
4. The browser deduplicates each generated command, opens the existing PowerShell terminal, and sends the exact validated command over the existing terminal WebSocket.
5. Pip or npm performs the installation in the application workspace while output streams in the terminal panel. The existing Stop action remains available.

## Alternatives considered

- **Run the full manifest command every time:** simplest and largely idempotent, but it performs unnecessary resolution and may rewrite lock state even when nothing is missing.
- **Preflight only without live execution:** precise, but still requires manual action and does not meet the automatic-install requirement.
- **Dedicated background installer API:** easier to model as a job, but loses the requested live CLI visibility and duplicates terminal lifecycle code.

## Safety and failure behavior

Only package names and version expressions accepted by the existing validators reach preflight or command construction. Subprocess preflight uses argument arrays, never `shell=True`. A failed preflight is treated as missing so the package manager can report the authoritative error in the visible terminal. Install failures remain visible and do not retry automatically during the same page session. Commands are capped at the existing 100-package limit.

## Verification

Tests will cover satisfied versus missing Python and Node dependencies, safe command construction, automatic terminal dispatch, duplicate suppression, and preservation of live streamed output. The full unit suite, JavaScript syntax validation, and a controlled browser scenario will run before completion.
