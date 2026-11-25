# Red-Team Readiness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver six independently released security and reliability fixes that make JSON_CODR truthfully ready for local browser and CLI coding.

**Architecture:** Add corroborated runtime identity, externalize mutable workspace state, replace the fixed bootstrap model with a digest-bound policy, harden development/production identity transitions, prove coding in a disposable repository, and introduce immutable multi-action approval envelopes. Each task is a complete release cycle and may not begin until the prior commit is pushed, pulled, reloaded, and live-tested.

**Tech Stack:** Python 3.15, FastAPI, PowerShell 7/Windows PowerShell, SQLite, Git/GitHub CLI, Ollama, unittest, in-app browser.

**Spec:** `docs/superpowers/specs/2026-11-24-redteam-readiness-hardening-design.md`

## Global Constraints

- Bind network services only to `127.0.0.1`.
- Preserve `.tmp/` contents until a hash-verified recoverable migration completes.
- Never relax dirty-tree, CSRF, exact-origin, project-root, Git lease, or rollback checks.
- Development Administrator and CLI credentials remain non-expiring and revocable until production mode is explicitly activated.
- A production transition must revoke every development browser and CLI credential.
- One fix per commit and live release cycle; no batching fixes into one commit.

## Review Focus

- A rogue listener on port 8765 must not be reported as the managed JSON_CODR build.
- Ignored or migrated workspace scratch must not become an executable/import source.
- Mutable Ollama tags must not substitute for the recorded model digest.
- IPv4/IPv6, Host, Origin, redirect, cookie, and CSRF variants must fail closed.
- Approval envelopes must reject scope expansion, replay, principal changes, project changes, and task-revision changes.

---

### Task 1: Truthful runtime identity and status

**Files:**
- Create: `web_app/core/runtime_status.py`
- Modify: `web_app/core/api.py`
- Modify: `web_app/app.py`
- Modify: `json_codr_launcher.py`
- Test: `test_core_api.py`
- Test: `test_run_web.py`

**Interfaces:**
- Produces: `build_runtime_status(store, *, environment, current_pid, now) -> dict[str, object]` with `health`, `management_state`, `revision`, `instance_id`, `started_at`, `manifest_digest`, and current-process evidence.

- [ ] Add regressions for a live unmanaged server, a matching managed heartbeat, a stale foreign heartbeat, and missing identity evidence.
- [ ] Run focused tests and capture RED failures.
- [ ] Implement server-derived status and launcher identity propagation without trusting caller headers.
- [ ] Run `python -m unittest -v test_core_api test_core_cli test_run_web test_update_launcher`.
- [ ] Commit, push, pull, restart, reload, and prove API/browser/CLI identity from the same SHA.

### Task 2: External runtime state and trusted-source cleanliness

**Files:**
- Create: `scripts/bootstrap/WorkspaceState.psm1`
- Modify: `bootstrap.ps1`
- Modify: `scripts/bootstrap/SourceTrust.psm1`
- Modify: `run_web.ps1`
- Modify: `.gitignore`
- Test: `test_bootstrap_source_trust.py`
- Test: `test_run_web.py`

**Interfaces:**
- Produces: a hash-verified migration receipt under `%LOCALAPPDATA%\JSON_CODR\migration-receipts` and a bootstrap repair path that never executes migrated content.

- [ ] Add regressions for repository-local logs/scratch, reparse points, hash mismatch, interrupted copy, and executable/import attempts from migrated scratch.
- [ ] Run focused tests and capture RED failures.
- [ ] Implement copy-verify-receipt migration, reserve the external runtime root, and keep source trust strict.
- [ ] Migrate the existing `.tmp/` contents recoverably and verify every hash before removing the source copy.
- [ ] Run `python -m unittest -v test_bootstrap_source_trust test_run_web test_workspace`.
- [ ] Commit, push, pull, restart, reload, and prove trusted bootstrap readiness plus browser/CLI smoke.

### Task 3: Digest-bound bootstrap model policy

**Files:**
- Modify: `config/bootstrap-models.json`
- Modify: `scripts/bootstrap/Proof.psm1`
- Create: `web_app/core/model_policy.py`
- Test: `test_bootstrap_source_trust.py`
- Test: `test_core_native_ollama.py`

**Interfaces:**
- Produces: model selection evidence containing policy version, model name, exact Ollama digest, capability-probe result, and fallback reason.

- [ ] Add regressions for missing preferred model, mutable-tag digest drift, failed coding probe, and valid fallback selection.
- [ ] Run focused tests and capture RED failures.
- [ ] Implement policy-ordered selection over installed reviewed coding models and a bounded local probe.
- [ ] Run `python -m unittest -v test_bootstrap_source_trust test_core_native_ollama test_inference_compatibility`.
- [ ] Commit, push, pull, restart, reload, and prove bootstrap plus live CLI inference uses the recorded digest.

### Task 4: Loopback authentication and production transition

**Files:**
- Modify: `web_app/core/identity.py`
- Modify: `web_app/core/cli_identity.py`
- Modify: `web_app/app.py`
- Test: `test_auth.py`
- Test: `test_identity_api.py`
- Test: `test_core_cli.py`

**Interfaces:**
- Produces: explicit `development`/`production` identity mode and an atomic production transition that revokes all development sessions and CLI credentials.

- [ ] Add hostile Host/Origin/IPv6/redirect/CSRF/cookie tests and production-transition revocation tests.
- [ ] Run focused tests and capture RED failures.
- [ ] Implement only missing guards; retain permanent revocable credentials in development mode.
- [ ] Run `python -m unittest -v test_auth test_identity test_identity_api test_core_cli test_web_api`.
- [ ] Commit, push, pull, restart, reload, and prove browser login, CSRF persistence, and CLI authentication.

### Task 5: Disposable real-coding verification

**Files:**
- Create: `scripts/verify-coding-workflow.ps1`
- Create: `test_coding_workflow_e2e.py`
- Modify: `scripts/verify-first-run.ps1`

**Interfaces:**
- Produces: a JSON verification receipt for create/edit/test/diff/commit/undo and negative escape fixtures, with the disposable root removed after hash/evidence capture.

- [ ] Add RED cases for junction/symlink escape, hostile Git hooks, crafted filenames, environment injection, and rollback mismatch.
- [ ] Implement the bounded verifier using a disposable repository and the real authenticated CLI/API path.
- [ ] Run the E2E verifier and affected command, coding-agent, terminal, Git, and worktree suites.
- [ ] Commit, push, pull, restart, reload, and repeat the verifier from the published SHA.

### Task 6: Single immutable approval envelope

**Files:**
- Modify: `web_app/core/approval.py`
- Modify: `web_app/core/agent_runtime.py`
- Modify: `web_app/core/api.py`
- Modify: `web/app.js`
- Test: `test_core_approval.py`
- Test: `test_agent_runtime.py`
- Test: `test_web_api.py`
- Test: `test_web_static.py`

**Interfaces:**
- Produces: an approval envelope binding a finite canonical-call set to principal, project fingerprint, task revision, expiry/revocation state, and consumption evidence.

- [ ] Add RED cases for repeated in-envelope calls, out-of-envelope calls, replay, revision drift, principal/project changes, destructive escalation, and concurrent consumption.
- [ ] Implement one preflight summary, exact envelope consumption, and a final receipt; keep destructive/network/publication/scope-expansion prompts separate.
- [ ] Run `python -m unittest -v test_core_approval test_agent_runtime test_core_api test_web_api test_web_static` plus the full suite.
- [ ] Commit, push, pull, restart, reload, and prove one browser workflow completes without repeat prompts.

### Final aggregate gate

- [ ] Run trusted bootstrap check, CLI status/auth/inference, disposable coding verification, full unittest discovery, JavaScript syntax, Python compilation, and `git diff --check`.
- [ ] Confirm local `main`, `origin/main`, live `/api/health`, and browser revision are identical.
- [ ] Record final evidence and publish the final hardening build without modifying retained recovery evidence.
