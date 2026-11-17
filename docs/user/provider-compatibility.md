# Provider compatibility layer

JSON_CODR updates optional programs through one lifecycle instead of letting chat, CLI, or agents install them directly. The lifecycle resolves an exact release, acquires it into an isolated version directory, verifies a live capability, activates it by generation, and retains the previous version for rollback.

REA is the reference implementation. To reinstall and verify an exact REA release:

```powershell
C:\Python315\python.exe -m web_app.core.rea_provider_update_cli --version 6.9.0 --data-root D:\JSON_CODR_alpha\.local-runtime
```

Use `--approve-major` only after reviewing a major-version change or downgrade. A successful command returns the activated version and generation plus live MCP evidence. Package presence alone is never reported as compatibility.

## Adding another program

Start from `scripts/provider_compatibility_template.py`. Keep program-specific package discovery and probing in the adapter, then register it with `CompatibilityLayer`.

An adapter must:

1. Resolve an exact immutable source identity and verify the package manager's lock or artifact digest.
2. Install into a unique staging directory without changing the active runtime.
3. Reject links, reparse points, path escapes, and mismatched package identity.
4. Start the candidate with an explicit executable and minimal environment.
5. Run a harmless real capability twice across a clean restart and record a SHA-256 evidence digest.
6. Activate with compare-and-swap generation control and acquire a runtime lease for each operation.
7. Quarantine failed candidates and retain the last-known-good version for rollback.

The shared layer rejects unknown providers, substituted identities, and activations without verification evidence. It does not turn a manifest claim into a capability claim.

## Files and recovery

Managed providers live below `<data-root>/providers/<provider-id>/`. Version directories are immutable after acquisition. SQLite is authoritative for activation generations and leases; `active.json` is an inspectable projection only. On restart, interrupted candidates are quarantined and staging directories are removed before another update is attempted.

Manual MCP configuration remains the fallback when no managed provider state exists. Once a managed REA activation exists, new operations resolve the current SQLite generation and hold a lease until their provider process closes.
