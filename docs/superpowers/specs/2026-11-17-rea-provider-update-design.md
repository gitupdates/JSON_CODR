# REA Provider Update Design

## Intent

JSON_CODR must update REA without replacing files loaded by an active Windows process, interrupting an investigation, changing the Python core environment, or advertising a release before real MCP and provider probes pass. Updates should normally complete in the background and preserve an inspectable last-known-good rollback.

## Goals

- Install each REA release into an immutable versioned provider directory.
- Discover, acquire, verify, stage, probe, activate, drain, roll back, and prune through one BORG service path.
- Keep active investigations bound to the REA process and version that created their retained Evidence.
- Route new sessions to a candidate only after its actual package, MCP server, tool catalog, skill, and applicable analysis providers pass verification.
- Record package provenance, npm integrity, server identity, catalog digest, probe evidence, activation history, and rollback reason.
- Recover deterministically after a process or host restart at every update state.
- Keep CLI access and the previous REA release available when a candidate fails.

## Non-goals

- Patching or copying REA internals into JSON_CODR.
- Updating Ghidra, Java, IDA, JADX, Node.js, or other analysis engines as a side effect of a REA update.
- Migrating retained in-memory Evidence between REA processes.
- Treating package installation, a successful version command, or a declared tool catalog as functional verification.
- Replacing active provider files in place.

## Constraints

- REA includes native Windows modules that cannot be moved or overwritten while loaded.
- A retained Evidence reference is scoped to the MCP connection that produced it unless explicitly exported.
- REA registrations and skills are version-coupled to the server release.
- The active server's MCP identity and tool list are authoritative; repository-main documentation may describe a newer release.
- BORG remains the task, policy, provenance, and routing authority. REA remains an external capability provider.
- CPU/Ollama coding functionality must remain usable when every REA release is unavailable.

## Approaches

### In-place global update

Stop REA, run `rea update`, refresh registrations, and restart. This is simple but interrupts work, reproduces Windows native-file locks, and has weak rollback. Rejected.

### Package-runner launch

Launch `npx -y rea-agents@<version> mcp` for each session. This gives exact version requests but makes availability depend on package-runner cache state and can acquire code during task startup. Retained only as an operator recovery path.

### Versioned blue/green providers

Install exact versions side by side, probe a candidate through its absolute Node entry script, atomically switch the active version for new sessions, and drain the old version. This avoids loaded-file replacement, supports offline restart and exact rollback, and matches BORG's existing provider isolation model. Selected.

## Storage layout

```text
<data-root>/providers/rea/
  state.sqlite
  active.json
  versions/
    6.9.0/
      installation/
      manifest.json
      package-lock.json
      skill/
      probe-evidence.json
    6.10.0/
      ...
  staging/
    <update-id>/
  logs/
```

`active.json` is a rebuildable convenience pointer. SQLite is authoritative for update state, activation generation, leases, and history. A version directory is immutable after verification. Staging and version paths must resolve beneath the provider root and may not be reparse points.

The current generic `ProviderManager.ensure()` replaces `<provider-id>` through a staging/backup rename and deletes the backup immediately. That implementation is suitable only for stopped providers and must not be reused for REA. The permanent provider lifecycle will gain version-addressed installations and leased activation generations; the existing behavior remains behind its current tests until each generic provider is deliberately migrated.

## Durable state machine

An update has one of these states:

```text
discovered -> acquiring -> staged -> verifying -> ready -> activating -> active
                                      |                     |
                                      v                     v
                                  quarantined           rolled_back
```

Draining and pruning are version states rather than update states. Every transition uses an expected revision and appends a BORG task event before acknowledging the side effect. Restart recovery inspects the durable state plus filesystem identity; it never infers success from directory presence alone.

## Discovery and trust

- Query npm metadata for an exact release without installing it.
- Record package name, exact version, tarball URL, npm `dist.integrity`, publication time, source repository, discovery time, and updater version.
- Accept only the configured `rea-agents` package and configured npm registry origin.
- Automatic activation is limited to a newer release on the currently trusted major version and source.
- A major-version change, registry/source change, missing integrity value, downgrade, or local source build requires visible approval.
- Discovery never executes package code.

## Acquisition

- Install the exact version under a fresh staging directory using a dedicated npm prefix.
- Do not write to the global npm installation or the JSON_CODR Python environment.
- Capture the resolved dependency lock and npm output as redacted artifacts.
- Verify the downloaded artifact against npm integrity through npm's package installer and record the resulting package tree digest.
- Reject symlinks or reparse-point escapes from the staging root.
- Promote staging to the immutable version directory only after acquisition validation succeeds.

## Candidate verification

Verification launches the candidate by absolute paths:

```text
<trusted-node> <version-root>/installation/node_modules/rea-agents/scripts/rea.mjs mcp
```

The candidate receives an explicit allowlisted environment for configured providers. Verification must establish:

1. The process starts and completes MCP initialization within the configured deadline.
2. `serverInfo` reports the expected REA version.
3. `tools/list` completes across every page and contains unique, valid schemas.
4. The catalog identity and counts are recorded; catalog changes are visible rather than assumed compatible.
5. The bundled skill exists and its declared version/tool count align with the running server.
6. A harmless real MCP call returns a structured result from the candidate.
7. Required BORG operations remain present. The required set is versioned configuration, not every historical REA tool.
8. Cancellation, graceful close, forced cleanup, stdout framing, stderr capture, and restart work.
9. Configured Ghidra, IDA, and JADX providers are inspected. An unavailable optional provider is recorded separately and does not falsify target-free REA readiness.
10. A call routed through `CoreService`, policy, `McpAdapter`, and the candidate returns the same Evidence identity and error semantics as a direct MCP call.

Probe results include exact runtime, package, catalog, skill, operating system, provider, and configuration identities. A failed or incomplete probe quarantines the candidate and leaves the active version untouched.

## Activation and session leases

- Activation is a compare-and-swap of the active generation in SQLite followed by an atomic rewrite of `active.json`.
- New MCP sessions read one active generation and acquire a lease on its version.
- A task retains that lease until the MCP connection closes, preserving same-session Evidence references.
- Activation never redirects an existing connection.
- The previous active version becomes `draining`; its files remain immutable and its process remains available to leased tasks.
- When its lease count reaches zero, BORG stops its idle process but retains its installation for rollback.

For same-major releases from the trusted source, activation is automatic only after every mandatory probe passes. Major/source/trust changes require approval. Settings may require approval for every activation but may not bypass probes.

## Post-activation health and rollback

- The first bounded number of real calls after activation are marked as a canary window.
- Startup failure, protocol failure, missing mandatory tool, repeated provider crash, invalid result framing, or failed canary causes an atomic rollback for new sessions.
- Existing successful sessions are not terminated solely because new-session routing rolled back.
- Rollback records the failed version, prior version, reason, task IDs, server/catalog identities, and evidence artifacts.
- A quarantined version cannot reactivate automatically without a new package identity or explicit reprobe after configuration repair.

## Retention and pruning

- Retain the active version, the previous last-known-good version, every leased version, and every version referenced by an unresolved update or rollback record.
- Pruning is a separate policy-controlled BORG task.
- Never delete a running or leased version.
- Version removal resolves and validates the exact provider-root target before deletion.
- Durable history and probe artifacts survive installation pruning.

## Skill handling

The matching bundled REA skill is copied into the version directory during acquisition. Activation switches the BORG skill projection to that exact copy in the same activation transaction. User edits are not overwritten; a customized skill remains a separate user-owned record and receives an update comparison rather than silent replacement.

## UI and operations

Settings exposes one REA provider row with active version, candidate version, update state, last check, last successful probe, provider availability, and rollback status. Routine same-major updates need no interaction. Details expose provenance, catalog changes, probe evidence, active leases, and retained rollback versions. Controls are Check, Reprobe, Activate when approval is required, Roll back, and Prune. They submit BORG tasks and do not perform package or process operations in handlers.

## Failure behavior

- Network or registry failure leaves the active provider unchanged and schedules bounded retry.
- Acquisition failure deletes only the validated staging directory and records diagnostics.
- Probe failure quarantines the candidate.
- Activation failure retains the previous active generation.
- Core shutdown closes provider processes but does not rewrite version state.
- Missing REA leaves unrelated JSON_CODR capabilities available and reports REA as unavailable.

## Security and provenance

- Package metadata never supplies an executable command; BORG constructs the launch from a trusted Node path and the verified package layout.
- Credentials are opaque references and are not inherited by REA unless a declared provider needs them.
- Environment variables use an allowlist and are recorded with secret values redacted.
- Update and provider actions obey the same project-independent system policy regardless of whether initiated by UI, schedule, chat, or CLI.
- Every candidate records npm integrity, package-tree digest, executable paths, configuration digest, server identity, catalog digest, skill identity, and probe artifacts.

## Verification

Tests cover concurrent discovery deduplication, interrupted acquisition recovery, immutable version directories, native-file lock avoidance, exact-version launch, paginated tool discovery, schema validation, skill alignment, failed probes leaving active unchanged, compare-and-swap activation, session leases, drain behavior, canary rollback, restart recovery, quarantine, pruning protection, major-version approval, environment redaction, and continued Ollama operation when REA fails.

A release is accepted only after focused tests, the existing provider/MCP/core tests, a live candidate probe through BORG, and a real REA target-free call pass. No synthetic tool list or placeholder Evidence may satisfy live acceptance.
