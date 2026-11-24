# First-Run Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a clean Windows 11 x64 JSON_CODR checkout install, configure, launch, and prove web, CLI, local inference, and optional GitHub readiness through one trustworthy command without Codex.

**Architecture:** A thin `bootstrap.ps1` invokes focused PowerShell modules for trusted-source validation, manifest-driven prerequisite planning, protected elevation, durable recovery, environment materialization, and end-to-end proofs. Python and PowerShell consume one canonical runtime configuration; the installed application runs from an immutable commit/tree-bound build under a stable unelevated supervisor.

**Tech Stack:** Windows PowerShell 5.1, Python 3.14+, FastAPI, DPAPI, WinGet, Git, GitHub CLI, Ollama, unittest, isolated Windows 11 x64 VM verification.

**Spec:** `docs/superpowers/specs/2026-11-24-first-run-bootstrap-design.md`

## Global Constraints

- Guaranteed host: Windows 11 x64 with inbox Windows PowerShell 5.1.
- Normal mode requires a clean Git checkout at a commit reachable from a configured trusted remote.
- `-DevelopmentSource` is visibly unverified and cannot issue readiness/release evidence or enable verified self-update.
- Install only manifest-allowlisted prerequisites through trusted WinGet sources; never pipe remote scripts or weaken host security.
- Create no global Python packages; consume committed hash locks in an isolated runtime environment.
- The application stays loopback-only and never kills an unrelated process occupying its port.
- Administrator account, password, browser sessions, and CLI credentials are non-expiring in initial non-production mode, remain revocable, and must be visibly labeled.
- Credentials remain in their owning stores and never enter logs, journals, receipts, or command lines.
- GitHub proof is read-only; no push, remote mutation, repository creation, or silent account selection.
- No step depends on Codex executables, credentials, directories, or runtime services.
- Preserve existing user data, accounts, Git state, active-build pointers, `.tmp/`, and unrelated processes.

## Review Focus

- A malicious or merely unrelated process on port 8765 must be diagnosed as a conflict, never reused or killed; Task 6 adds nonce/challenge and ownership tests.
- Cancellation or power loss after elevation, environment promotion, or supervisor launch must deterministically resume without trusting `running`; Tasks 3, 4, and 6 add interruption tests.
- Dirty, ZIP, detached, wrong-remote, and non-Codex machines must produce honest source/readiness states; Tasks 1 and 8 test these paths.
- Wrong-publisher, stale-version, proxy/TLS, partial-download, disk-full, and reboot-required installs must remain bounded and recoverable; Tasks 2 and 3 test them.
- Existing identities, credentials, data roots, and launcher pointers must be reused or blocked without overwrite; Tasks 5 and 6 add existing-install reconciliation tests.

---

### Task 1: Canonical Runtime Configuration and Trusted Source

**Files:**
- Create: `config/runtime.json`
- Create: `web_app/runtime_config.py`
- Create: `scripts/bootstrap/SourceTrust.psm1`
- Modify: `run_web.ps1`
- Modify: `web_app/core/cli.py`
- Modify: `web_app/version.py`
- Test: `test_runtime_config.py`
- Test: `test_bootstrap_source_trust.py`
- Modify: `test_run_web.py`
- Modify: `test_version.py`

**Interfaces:**
- Produces: `RuntimeConfig.load(path: Path | None = None) -> RuntimeConfig`, `RuntimeConfig.receipt_digest() -> str`, and PowerShell `Get-JsonCodrSourceEvidence -Root <path> -DevelopmentSource:<bool>`.
- Runtime schema includes `schema_version`, `version`, `host`, `port`, API paths, Python ranges, default roots, and allowed environment overrides.

- [ ] **Step 1: Write failing configuration tests** asserting launcher, CLI default URL, health paths, and version all resolve from `config/runtime.json`, and unknown overrides fail validation.
- [ ] **Step 2: Run the focused tests** with `python -m unittest test_runtime_config.py test_run_web.py test_version.py -v`; expect failures showing independent hardcoded values.
- [ ] **Step 3: Implement the canonical runtime loader and convert Python/PowerShell consumers** without changing loopback host or port 8765.
- [ ] **Step 4: Write failing source-trust tests** for clean reachable commit, dirty tree, detached unreachable commit, wrong remote, no `.git`, development override, spaces, and non-ASCII paths.
- [ ] **Step 5: Implement `Get-JsonCodrSourceEvidence`** returning normalized remote, commit, tree, manifest digest, trust state, and reason without mutating Git.
- [ ] **Step 6: Run focused tests and syntax checks**; expect all Task 1 tests pass and `git diff --check` succeeds.
- [ ] **Step 7: Commit** with `feat(bootstrap): establish canonical runtime and source trust`.

### Task 2: Allowlisted Prerequisite Manifest and Planner

**Files:**
- Create: `config/bootstrap-prerequisites.json`
- Create: `config/bootstrap-models.json`
- Create: `requirements-lock.txt`
- Create: `scripts/bootstrap/Manifest.psm1`
- Create: `scripts/bootstrap/Planner.psm1`
- Test: `test_bootstrap_manifest.py`
- Test: `test_bootstrap_planner.py`

**Interfaces:**
- Consumes: canonical runtime and trusted-source evidence from Task 1.
- Produces: `Import-JsonCodrBootstrapManifest`, `Get-JsonCodrBootstrapPlan`, and canonical plan/result objects with versioned schemas.

- [ ] **Step 1: Write failing manifest tests** for schema/version, Windows 11 x64, exact WinGet source/package IDs, publishers, version bounds, architecture, installer scope/flags, executable probes, disk bounds, committed lock digest, and reviewed model identity/size/license metadata.
- [ ] **Step 2: Write failing planner tests** for installed/missing/old/corrupt/wrong-publisher components, optional provider Python, insufficient disk, PATH refresh, no model, proxy environment, and noninteractive confirmation.
- [ ] **Step 3: Run focused tests**; expect missing modules/manifests.
- [ ] **Step 4: Implement manifest validation and a read-only planner** that resolves executable paths, never regenerates trust inputs, and emits deterministic install/probe actions.
- [ ] **Step 5: Generate and review the hash-locked host dependency artifact** for supported Python/architecture markers; test installation with `--require-hashes` in a disposable environment.
- [ ] **Step 6: Run Task 2 tests and `git diff --check`**; expect pass.
- [ ] **Step 7: Commit** with `feat(bootstrap): plan trusted prerequisites`.

### Task 3: Protected Installation, Elevation, and Recovery Journal

**Files:**
- Create: `scripts/bootstrap/State.psm1`
- Create: `scripts/bootstrap/Elevation.psm1`
- Create: `scripts/bootstrap/Install.psm1`
- Test: `test_bootstrap_state.py`
- Test: `test_bootstrap_install.py`

**Interfaces:**
- Consumes: versioned plan object from Task 2.
- Produces: `Open-JsonCodrBootstrapRun`, `Invoke-JsonCodrElevatedPlan`, `Invoke-JsonCodrInstallPlan`, and atomic sanitized phase receipts.

- [ ] **Step 1: Write failing journal/lock tests** for PID plus process-start ownership, heartbeat, proven-dead stale recovery, atomic records, redaction, concurrent run refusal, and interrupted `running` reprobe.
- [ ] **Step 2: Write failing elevation tests** for protected ACL, nonce/digest binding, manifest-bounded operations, replay, tampering, UAC cancellation, and forbidden application/account operations.
- [ ] **Step 3: Write failing installation tests** for source/publisher disagreement, agreement flags, bounded timeouts, offline/proxy/TLS failures, partial cleanup, disk full, reboot required, pre-existing components, and no automatic continuation.
- [ ] **Step 4: Run focused tests**; expect missing state/elevation/install functions.
- [ ] **Step 5: Implement durable state and protected elevation** using atomic replace/write-through semantics and independently reprobed results.
- [ ] **Step 6: Implement allowlisted WinGet installation** without global policy changes or arbitrary-download fallback.
- [ ] **Step 7: Run Task 3 tests and PowerShell parser checks**; expect pass.
- [ ] **Step 8: Commit** with `feat(bootstrap): install prerequisites transactionally`.

### Task 4: Immutable Application Environment and Build Materialization

**Files:**
- Create: `scripts/bootstrap/Materialize.psm1`
- Modify: `json_codr_launcher.py`
- Modify: `run_web.ps1`
- Test: `test_bootstrap_materialize.py`
- Modify: `test_update_supervisor.py`

**Interfaces:**
- Consumes: source evidence, canonical config, prerequisite paths, dependency lock, and bootstrap journal.
- Produces: immutable build receipt containing commit, tree, config digest, dependency-lock digest, interpreter identity, environment ID, and build root.

- [ ] **Step 1: Write failing tests** for clean commit materialization, exact tree binding, venv isolation, hash enforcement, dependency drift, atomic promotion, interrupted promotion, prior-build preservation, development-source labeling, and paths with spaces/non-ASCII.
- [ ] **Step 2: Run focused tests**; expect missing materializer.
- [ ] **Step 3: Implement environment ID computation and isolated locked dependency installation** using resolved interpreter paths.
- [ ] **Step 4: Implement immutable Git build materialization and atomic promotion** without executing from the mutable checkout in trusted mode.
- [ ] **Step 5: Bind the stable launcher to verified build receipts** while preserving existing active pointers on conflict.
- [ ] **Step 6: Run Task 4 and supervisor tests**; expect pass and no leaked child processes.
- [ ] **Step 7: Commit** with `feat(bootstrap): materialize verified application builds`.

### Task 5: Non-Production Administrator and CLI Provisioning

**Files:**
- Modify: `web_app/core/identity.py`
- Modify: `web_app/core/cli_identity.py`
- Modify: `web_app/core/cli.py`
- Modify: `web_app/app.py`
- Create: `scripts/bootstrap/Identity.psm1`
- Test: `test_bootstrap_identity.py`
- Modify: `test_cli_identity.py`
- Modify: `test_auth.py`

**Interfaces:**
- Consumes: healthy local installation origin from Tasks 1–4.
- Produces: supported bootstrap identity API, permanent full Administrator, non-expiring-but-revocable browser/CLI credentials, and visible non-production policy status.

- [ ] **Step 1: Write failing tests** for secure interactive password input, no temporary password, permanent full Administrator, non-expiring sessions/CLI credentials, manual revocation, existing-account reconciliation, noninteractive action-required, structural secret redaction, and visible non-production labels.
- [ ] **Step 2: Run focused tests**; expect current expiration/bootstrap behavior failures.
- [ ] **Step 3: Implement an authenticated loopback bootstrap-identity protocol** that is one-time, installation-bound, and unavailable after initialization; never edit the database directly.
- [ ] **Step 4: Implement the initial non-production credential policy** without adding the future production-mode conversion.
- [ ] **Step 5: Implement PowerShell secure prompting and CLI login/status proof** without putting secrets on command lines.
- [ ] **Step 6: Run Task 5 tests**; expect pass and no secret material in captured output.
- [ ] **Step 7: Commit** with `feat(bootstrap): provision permanent local administrator`.

### Task 6: Stable Lifecycle, Challenge Health, and Local Readiness

**Files:**
- Modify: `json_codr_launcher.py`
- Modify: `web_app/app.py`
- Create: `scripts/bootstrap/Lifecycle.psm1`
- Create: `scripts/bootstrap/Proof.psm1`
- Test: `test_bootstrap_lifecycle.py`
- Test: `test_bootstrap_proof.py`
- Modify: `test_update_supervisor.py`

**Interfaces:**
- Consumes: verified build and identity receipts.
- Produces: detached unelevated supervisor lifecycle commands, authenticated nonce health challenge, and web/CLI/Ollama/restart proof receipts.

- [ ] **Step 1: Write failing lifecycle tests** for detached start, status/stop/restart ownership, console exit survival, existing supervisor reuse, pointer conflict, unrelated port owner, false health responder, stale challenge, and bounded logs.
- [ ] **Step 2: Write failing proof tests** for version/config/revision/tree agreement, browser/static assets, default CLI URL, DPAPI credential status, fixed bounded inference task, Ollama protocol/model proof, restart persistence, timeout/error classifications, and cleanup of only owned processes.
- [ ] **Step 3: Run focused tests**; expect missing lifecycle/proof functions.
- [ ] **Step 4: Implement installation-bound nonce health challenge** with freshness, process-start identity, revision/tree, and config digest.
- [ ] **Step 5: Implement detached stable-supervisor lifecycle** under the unelevated user with exact management commands.
- [ ] **Step 6: Implement mandatory local readiness and restart proofs**; `-NoStart` must return action-required and no readiness receipt.
- [ ] **Step 7: Run Task 6 tests and existing launcher/update tests**; expect pass and port 8765 unrelated-process tests prove no kill/reuse.
- [ ] **Step 8: Commit** with `feat(bootstrap): prove stable local readiness`.

### Task 7: GitHub Readiness and Bootstrap Orchestrator

**Files:**
- Create: `scripts/bootstrap/GitHub.psm1`
- Create: `bootstrap.ps1`
- Modify: `web_app/github_cli.py`
- Test: `test_bootstrap_github.py`
- Test: `test_bootstrap_entrypoint.py`
- Modify: `test_github_cli.py`

**Interfaces:**
- Consumes: Tasks 1–6 modules and receipts.
- Produces: one public bootstrap command, stable exit classifications, versioned JSON result, optional read-only GitHub proof, and exact resume/repair commands.

- [ ] **Step 1: Write failing GitHub tests** for missing CLI, signed out, login cancellation, multiple accounts/remotes, wrong host/account, denied scope, no remote, normalized remote match, sanitized `gh api user`, `git ls-remote`, and `-NoGitHub` local-only success.
- [ ] **Step 2: Write failing entrypoint tests** for default/check/repair/no-start/no-GitHub/development-source/JSON modes, stdout/stderr separation, noninteractive action-required, stable exit codes, resume commands, and phase ordering.
- [ ] **Step 3: Run focused tests**; expect missing orchestrator.
- [ ] **Step 4: Implement read-only explicit GitHub selection and proof** using `gh` credential ownership.
- [ ] **Step 5: Implement thin `bootstrap.ps1` orchestration** with one elevation, deterministic recovery, structural redaction, and final READY/LOCAL ONLY/ACTION REQUIRED/BLOCKED classifications.
- [ ] **Step 6: Run Task 7 tests and PowerShell parser checks**; expect pass.
- [ ] **Step 7: Commit** with `feat(bootstrap): add one-command first-run setup`.

### Task 8: Documentation, No-Codex VM Proof, and Release Gate

**Files:**
- Modify: `README.md`
- Create: `docs/user/first-run.md`
- Create: `scripts/verify-first-run.ps1`
- Create: `.github/workflows/windows-first-run.yml`
- Test: `test_bootstrap_documentation.py`
- Test: `test_bootstrap_no_codex.py`

**Interfaces:**
- Consumes: public bootstrap and result schemas from Task 7.
- Produces: primary one-command documentation, CI deterministic checks, and sanitized Windows 11 x64 VM release evidence.

- [ ] **Step 1: Write failing documentation tests** asserting the bootstrap command is primary, manual setup is troubleshooting, version text derives from canonical config, and trusted changes/UAC/model/GitHub/local-only/repair/uninstall boundaries are explained.
- [ ] **Step 2: Write failing no-Codex/environment tests** asserting absence of Codex executables/directories/credentials and detecting any runtime dependency on them.
- [ ] **Step 3: Run focused tests**; expect missing documentation and verification script.
- [ ] **Step 4: Update README and write the first-run operator guide** with exact status/start/stop/restart/check/repair commands.
- [ ] **Step 5: Implement the Windows verification script and CI workflow** for deterministic logic; never expose VM receipts or credentials.
- [ ] **Step 6: Run focused repository tests, PowerShell/Node/Python syntax checks, and `git diff --check`**; expect pass.
- [ ] **Step 7: Run a clean Windows 11 x64 VM proof** from trusted clone through model confirmation, permanent Administrator creation, web/CLI/Ollama/GitHub proof, restart, repair rerun, and sanitized receipt; confirm no Codex installation exists.
- [ ] **Step 8: Perform interruption recovery probes** after elevation, environment promotion, and supervisor launch; expect deterministic resume and no user-state loss.
- [ ] **Step 9: Commit** with `feat(setup): deliver verified first-run bootstrap`.

## Final Verification

- [ ] Run the complete focused bootstrap, identity, launcher, CLI, Ollama, and GitHub suite.
- [ ] Run existing security/update regression tests affected by canonical configuration and supervisor changes.
- [ ] Verify no secrets in test artifacts, journals, logs, receipts, Git diff, or process command lines.
- [ ] Verify only the pre-existing `.tmp/` remains unrelated and untracked.
- [ ] Request a fresh whole-branch security and first-run review against the spec.
- [ ] Accept no release claim until the clean Windows 11 x64 VM receipt proves the documented command end to end.
