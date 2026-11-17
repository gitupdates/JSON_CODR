# REA Provider Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable blue/green REA updater that installs exact releases side by side, verifies real MCP behavior, atomically activates candidates for new sessions, preserves leased sessions, and rolls back safely.

**Architecture:** A REA-specific repository owns SQLite lifecycle state and immutable version directories; a service coordinates acquisition, verification, activation, leases, canary health, and pruning through injected installer/probe boundaries. The existing generic provider manager remains unchanged. The active provider projection is consumed by the stdio MCP adapter so BORG remains the sole routing authority.

**Tech Stack:** Python 3.15, SQLite, asyncio, npm prefix installations, existing `StdioMcpBackend`, Pydantic contracts, unittest.

**Spec:** `docs/superpowers/specs/2026-11-17-rea-provider-update-design.md`

## Global Constraints

- Never replace or delete files belonging to an active or leased REA version.
- SQLite is authoritative; `active.json` is an atomic, rebuildable projection.
- Exact package version, npm integrity, launch path, catalog digest, and probe evidence are mandatory before activation.
- Same-major trusted upgrades may activate automatically; major changes, downgrades, source changes, and missing integrity require approval.
- Existing MCP sessions remain pinned to their acquired version until release.
- REA failure must not affect Ollama or unrelated JSON_CODR capabilities.
- The generic `ProviderManager.ensure()` behavior is not reused or changed.

## Review Focus

- Two callers discovering or staging the same version concurrently must produce one durable candidate and no partial version directory (Task 2).
- A restart during acquisition or activation must leave the prior active generation authoritative and make the interrupted candidate recoverable or quarantined (Tasks 2 and 4).
- A leased old version must remain launchable and unprunable after a new activation (Tasks 3 and 5).
- A valid package whose live MCP identity, schema catalog, or required tools disagree must be quarantined without changing active routing (Task 3).
- A canary failure racing with a newer activation must use generation compare-and-swap and never roll back the wrong generation (Task 4).

---

### Task 1: Durable REA lifecycle contracts and repository

**Files:**
- Create: `web_app/core/rea_provider_state.py`
- Create: `test_rea_provider_state.py`

**Interfaces:**
- Produces: `ReaCandidate`, `ReaActivation`, `ReaLease`, `ReaProviderStore`, `RevisionConflict`.
- Produces repository methods `discover`, `transition`, `activate`, `acquire_lease`, `release_lease`, `quarantine`, `record_canary_failure`, `versions`, and `recover`.

- [ ] **Step 1: Write failing repository tests** for state transitions, optimistic revision rejection, activation generation compare-and-swap, lease counts, restart recovery, and canary rollback generation safety.
- [ ] **Step 2: Run `C:\Python315\python.exe -m unittest test_rea_provider_state.py -v` and verify import/test failures.**
- [ ] **Step 3: Implement immutable contracts and the SQLite repository** with WAL, foreign keys, transaction locking, explicit allowed transitions, and store-assigned event sequence/identity.
- [ ] **Step 4: Run the focused test and verify all repository cases pass.**

### Task 2: Safe exact-version acquisition

**Files:**
- Create: `web_app/core/rea_acquisition.py`
- Create: `test_rea_acquisition.py`
- Modify: `web_app/core/rea_provider_state.py`

**Interfaces:**
- Consumes: `ReaProviderStore` transition methods from Task 1.
- Produces: `ReaReleaseMetadata`, `ReaAcquirer.acquire(metadata) -> Path`, `NpmReaInstaller`.

- [ ] **Step 1: Write failing tests** for trusted registry validation, exact version/integrity requirements, path containment, reparse/symlink rejection, concurrent acquisition deduplication, interrupted staging recovery, immutable promotion, and redacted artifacts.
- [ ] **Step 2: Run `C:\Python315\python.exe -m unittest test_rea_acquisition.py -v` and verify failures.**
- [ ] **Step 3: Implement acquisition** using a unique validated staging root, injected installer, package-tree digest, immutable promotion, and durable transitions; add the production npm-prefix installer without executing metadata-supplied commands.
- [ ] **Step 4: Run the focused acquisition and state tests and verify they pass.**

### Task 3: Live MCP candidate verification and session leases

**Files:**
- Create: `web_app/core/rea_verification.py`
- Create: `test_rea_verification.py`
- Modify: `web_app/core/mcp_stdio_backend.py`
- Modify: `web_app/core/rea_provider_state.py`

**Interfaces:**
- Consumes: acquired immutable version path and `StdioMcpBackend`.
- Produces: `ReaProbePolicy`, `ReaProbeEvidence`, `ReaCandidateVerifier.verify(version)`, and `LeasedReaBackend`.

- [ ] **Step 1: Write failing tests** for exact launch paths, expected server version, paginated unique tool schemas, required-tool enforcement, catalog digest, bundled-skill alignment, harmless real-call result, clean restart, quarantine on mismatch, and lease pin/release behavior.
- [ ] **Step 2: Run `C:\Python315\python.exe -m unittest test_rea_verification.py -v` and verify failures.**
- [ ] **Step 3: Expose read-only server/stderr identity from `StdioMcpBackend` and implement verifier/leased backend** so no synthetic catalog or placeholder Evidence can pass.
- [ ] **Step 4: Run verification, stdio backend, and state tests and verify they pass.**

### Task 4: Update orchestration, activation, and rollback

**Files:**
- Create: `web_app/core/rea_update_service.py`
- Create: `test_rea_update_service.py`
- Modify: `web_app/core/mcp_stdio_backend.py`

**Interfaces:**
- Consumes: store, acquirer, verifier, and active-generation leases.
- Produces: `ReaUpdateService.check`, `install`, `activate`, `open_backend`, `report_canary`, `rollback`, and `recover`.

- [ ] **Step 1: Write failing service tests** for discovery deduplication, approval rules, probes-before-activation, atomic active projection, activation failure, existing-session drain, canary rollback, stale-generation rejection, restart recovery, and REA-unavailable isolation.
- [ ] **Step 2: Run `C:\Python315\python.exe -m unittest test_rea_update_service.py -v` and verify failures.**
- [ ] **Step 3: Implement the coordinator** with injected registry/acquisition/probe boundaries, atomic `active.json` replacement after SQLite CAS, and lease-aware backend creation.
- [ ] **Step 4: Run update-service and all preceding focused tests and verify they pass.**

### Task 5: Retention, configuration, and BORG wiring

**Files:**
- Modify: `web_app/core/rea_update_service.py`
- Modify: `web_app/core/mcp_stdio_backend.py`
- Modify: `web_app/app.py`
- Create: `test_rea_provider_integration.py`
- Modify: `test_web_api.py`

**Interfaces:**
- Consumes: `ReaUpdateService.open_backend()` and retained version state.
- Produces: active REA capability registration from provider state, `prune`, and backward-compatible manual MCP configuration fallback.

- [ ] **Step 1: Write failing integration tests** proving active version routing, manual-config fallback, leased/last-good/unresolved pruning protection, missing-REA isolation, and app shutdown cleanup.
- [ ] **Step 2: Run the focused integration tests and verify failures.**
- [ ] **Step 3: Wire the service into app startup/shutdown and MCP adapter construction** while leaving manual `mcp_servers.json` support and unrelated capabilities unchanged.
- [ ] **Step 4: Run `C:\Python315\python.exe -m unittest test_rea_provider_integration.py test_web_api.py test_mcp_stdio_backend.py -v` and verify passes.**

### Task 6: Live acceptance and regression verification

**Files:**
- Modify only if a verified defect is found in the preceding implementation.

**Interfaces:**
- Consumes: complete updater and the installed REA release.
- Produces: real probe evidence under the local data root; no committed machine-specific paths or artifacts.

- [ ] **Step 1: Run all focused provider/MCP/core tests** and correct only demonstrated failures.
- [ ] **Step 2: Run `C:\Python315\python.exe -m unittest discover -v` and verify the existing suite plus new tests passes.**
- [ ] **Step 3: Stage the currently installed exact REA release through the updater, run a target-free MCP call through BORG, verify the catalog/server/skill identities, and activate it.**
- [ ] **Step 4: Restart the local service using only its captured PID, verify `/api/health`, the REA capability, and a normal Ollama request, then confirm rollback remains available.**
