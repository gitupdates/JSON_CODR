# Staged Autonomous Self-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make JSON_CODR capable of automatically preparing, verifying, publishing, activating, and rolling back its own updates without granting models unrestricted host or GitHub authority.

**Architecture:** Extend the existing identity, policy, task-event, Git broker, and worktree services with a single durable candidate controller. Models may propose bounded changes, while server-owned registries, verification profiles, a scoped service identity, and a stable launcher perform every privileged transition. Automatic activation remains disabled until the complete verified lifecycle passes end-to-end tests.

**Tech Stack:** Python 3.15, FastAPI, Pydantic, SQLite, Git/GitHub CLI, Windows DPAPI, PowerShell launcher, `unittest`, existing JSON_CODR task/event store.

**Spec:** `docs/superpowers/specs/2026-11-23-staged-autonomous-self-update-design.md`

## Global Constraints

- Models never receive raw GitHub, browser-session, CLI, verifier, or self-update service credentials.
- Mutation routes require a verified principal and concrete scope; `X-JSON-CODR: 1` never authorizes a mutation.
- Policy derives canonical operations from a server-owned registry, not caller-provided labels.
- Autonomous commands use named verification profiles only; generic shell remains Administrator-interactive.
- Candidates modify only dedicated Git worktrees and never copy files into the live checkout.
- Commit and push require a manifest for the exact final tree and successful mandatory checks.
- No force push, dirty live update, unresolved merge/rebase, or irreversible unattended migration.
- Candidate health uses a separate loopback port and disposable data root.
- Rollback switches a launcher-owned active-build pointer; it never resets a user checkout.
- Existing supervised chat, CLI, Ollama, hardware, skills, REA, Ghidra, GitHub, and Designer flows remain available.

## Review Focus

- A caller pairs `native.shell` or `native.write` with `operation="read"`; Task 2 must reject it before policy evaluation.
- A verification profile marked no-network attempts a network executable or unreviewed command; Task 3 must deny it rather than claim unenforced isolation.
- A candidate changes after verification or verification is omitted; Task 4 must invalidate or reject commit/push.
- The remote branch moves or a push result is ambiguous; Task 6 must reconcile by commit SHA without duplicating publication.
- Candidate activation or a migration health check fails; Task 7 must keep or restore the previous known-good build.

---

## File structure

- `web_app/core/http_identity.py`: reusable FastAPI principal, scope, and CSRF dependencies.
- `web_app/core/capability_registry.py`: immutable capability-to-operation/risk definitions.
- `web_app/core/verification_profiles.py`: trusted named command profiles and manifest digesting.
- `web_app/core/autonomous_update.py`: durable candidate lifecycle and transition rules.
- `web_app/core/update_launcher.py`: active-build pointer contract and launcher receipts.
- `json_codr_launcher.py`: stable process boundary outside replaceable build directories.
- `web_app/app.py`: thin authenticated route wiring only.
- `web_app/core/policy.py`, `service.py`, `native_primitives.py`, `command_runtime.py`: normalized policy and restricted execution.
- `web_app/git_broker.py`, `github_cli.py`: verified publication, CAS push, abort/reconciliation.
- `run_web.ps1`: launch through the stable launcher while retaining direct development mode.
- Existing focused `test_*.py` modules are extended at the lowest owning layer.

### Task 1: Authenticate and scope every mutation route

**Files:**
- Create: `web_app/core/http_identity.py`
- Modify: `web_app/app.py:137-170,1559-2334`
- Modify: `web_app/core/identity.py`
- Test: `test_identity_api.py`
- Create: `test_github_api.py`
- Test: `test_coding_agents.py`

**Interfaces:**
- Consumes: `IdentityService.resolve_credential(raw_token, required_kind, required_scope)`.
- Produces: `MutationAuthorizer.principal(request, scope) -> AuthenticatedPrincipal` and `MutationAuthorizer.csrf(request) -> None`.

- [ ] **Step 1: Write failing endpoint tests** proving Git commit/push, broker grant/task, coding-agent grant/launch, terminal write, component install, promotion, activation, and rollback return `401` without credentials, `403` with wrong scope, and accept the correct browser or service scope plus CSRF where applicable.
- [ ] **Step 2: Run focused tests** with `C:\Python315\python.exe -m unittest test_identity_api.py test_github_api.py test_coding_agents.py`; expect failures showing mutation routes still accept the static header.
- [ ] **Step 3: Add `MutationAuthorizer`** and identity scopes `git.read`, `git.edit`, `git.commit`, `git.push`, `agent.launch`, `terminal.write`, `component.install`, `system.update`, `system.activate`, and `system.rollback`.
- [ ] **Step 4: Replace mutation header guards** with the dependency; retain the static header only on enumerated read-only compatibility routes and emit a deprecation response header.
- [ ] **Step 5: Run the focused tests** and expect all authentication, scope, and CSRF cases to pass.
- [ ] **Step 6: Commit** with `git commit -m "fix(identity): authenticate all mutation routes"`.

### Task 2: Make capability risk classification immutable

**Files:**
- Create: `web_app/core/capability_registry.py`
- Modify: `web_app/core/adapters.py:11-30`
- Modify: `web_app/core/policy.py:25-100`
- Modify: `web_app/core/service.py:89-155`
- Modify: `web_app/app.py:1970-1994`
- Create: `test_core_policy.py`
- Test: `test_core_service.py`
- Test: `test_core_native_primitives.py`

**Interfaces:**
- Produces: `CapabilityDefinition(capability_id: str, operation: str, risk: str, autonomous: bool)` and `CapabilityRegistry.resolve(capability_id: str) -> CapabilityDefinition`.
- Produces: `CapabilityRegistry.normalize(call: CapabilityCall) -> CapabilityCall`, rejecting a mismatched compatibility `operation`.

- [ ] **Step 1: Add failing spoofing tests** for `native.shell`, `native.write`, `native.edit`, `git.execute`, activation, and rollback paired with `operation="read"`; assert rejection before adapter execution.
- [ ] **Step 2: Run** `C:\Python315\python.exe -m unittest test_core_policy.py test_core_service.py test_core_native_primitives.py`; expect the spoofed calls to execute or request the wrong policy.
- [ ] **Step 3: Implement the registry** with exact canonical mappings from the spec and require all registered adapters to declare definitions at startup.
- [ ] **Step 4: Normalize in `CoreService.start`** before policy evaluation and persist only canonical operation values in events and grants.
- [ ] **Step 5: Constrain persistent grants** with expiry and a canonical argument-constraint digest; migrate existing unconstrained grants to disabled legacy records.
- [ ] **Step 6: Run focused tests** and expect spoofing, unknown capability, grant-expiry, and adapter-registration cases to pass.
- [ ] **Step 7: Commit** with `git commit -m "fix(policy): bind capabilities to canonical operations"`.

### Task 3: Restrict autonomous command execution to trusted profiles

**Files:**
- Create: `web_app/core/verification_profiles.py`
- Modify: `web_app/core/command_runtime.py`
- Modify: `web_app/core/native_primitives.py:56-74`
- Modify: `web_app/core/identity.py`
- Create: `test_core_command_runtime.py`
- Test: `test_core_native_primitives.py`
- Test: `test_verification_profiles.py`

**Interfaces:**
- Produces: `VerificationProfile(profile_id, executable, argument_template, cwd_rule, timeout_seconds, max_output_bytes, network_policy)`.
- Produces: `VerificationProfileStore.resolve(profile_id: str) -> VerificationProfile` and `profile_digest() -> str`.
- Changes autonomous shell input to `profile_id` plus typed template values; raw `argv` remains interactive-Administrator only.

- [ ] **Step 1: Add failing tests** for raw autonomous argv, PowerShell/cmd interpreters, absolute-path arguments, unapproved environment keys, profile tampering, and a no-network profile requesting a network-capable command.
- [ ] **Step 2: Run** `C:\Python315\python.exe -m unittest test_core_command_runtime.py test_core_native_primitives.py test_verification_profiles.py`; expect unsafe commands to be accepted.
- [ ] **Step 3: Implement Administrator-owned profile storage** below the application data root, atomic writes, canonical digesting, and separate profile-administration scope.
- [ ] **Step 4: Split command execution modes** into `run_interactive_admin(...)` and `run_profile(...)`; return only isolation claims actually enforced.
- [ ] **Step 5: Reject no-network profiles** until an enforcing sandbox adapter is configured; do not infer isolation from a Boolean flag.
- [ ] **Step 6: Run focused tests** and expect every hostile command/profile case to pass.
- [ ] **Step 7: Commit** with `git commit -m "fix(runtime): restrict autonomous commands to profiles"`.

### Task 4: Require final-tree verification before commit or push

**Files:**
- Modify: `web_app/models.py:41-97`
- Modify: `web_app/git_broker.py:163-259`
- Modify: `web_app/core/git_adapter.py`
- Test: `test_git_broker.py`
- Create: `test_core_git_adapter.py`

**Interfaces:**
- Produces: `VerificationReceipt(candidate_id, base_sha, tree_sha, profile_digest, checks, verified_at, verifier_credential_id)`.
- `GitBrokerService.execute(...)` accepts a trusted receipt reference for commit/push and revalidates the final tree immediately before each mutation.

- [ ] **Step 1: Add failing workflow tests** for omitted verify, failed verify, edit after verify, apply/commit/apply/push, uncommitted paths, verifier identity mismatch, and changed profile digest.
- [ ] **Step 2: Run** `C:\Python315\python.exe -m unittest test_git_broker.py test_core_git_adapter.py`; expect unsafe workflows to pass validation.
- [ ] **Step 3: Tighten `BrokerActionRequest` ordering** so verify is mandatory, final among tree-changing actions, and immediately precedes commit; no tree-changing action may follow commit.
- [ ] **Step 4: Compute Git tree SHA** after checks, issue a verifier-scoped receipt, and compare it again before commit and push.
- [ ] **Step 5: Require a clean candidate worktree after commit** and ensure the commit tree equals the receipt tree.
- [ ] **Step 6: Run focused tests** and expect all verification bypasses to be rejected.
- [ ] **Step 7: Commit** with `git commit -m "fix(git): require verified final tree for publication"`.

### Task 5: Add durable isolated candidate lifecycle

**Files:**
- Create: `web_app/core/autonomous_update.py`
- Modify: `web_app/core/store.py`
- Modify: `web_app/core/worktree_runtime.py`
- Modify: `web_app/core/agent_runtime.py`
- Test: `test_autonomous_update.py`
- Create: `test_core_worktree_runtime.py`
- Test: `test_core_store.py`

**Interfaces:**
- Produces: `AutonomousUpdateController.propose(profile_id, prompt, principal) -> CandidateRecord`.
- Produces: idempotent `stage`, `verify`, `commit`, `publish`, `health_check`, `activate`, `rollback`, and `reconcile` commands keyed by candidate ID and transition.
- Candidate events use `TaskEventDraft`; no mutable JSON file is authoritative.

- [ ] **Step 1: Add failing lifecycle tests** covering every allowed transition, forbidden skips, duplicate commands, restart recovery, two writers, dirty source, symlinks/reparse points, untracked additions, and deletions.
- [ ] **Step 2: Run** `C:\Python315\python.exe -m unittest test_autonomous_update.py test_core_worktree_runtime.py test_core_store.py`; expect missing controller and incomplete worktree behavior.
- [ ] **Step 3: Implement candidate contracts and state projection** on the existing task/event store with outbox-style effect receipts.
- [ ] **Step 4: Replace process-local writer locks** with an OS-visible repository lock carrying owner PID, candidate ID, creation, and expiry; recover only after verified owner death.
- [ ] **Step 5: Make worktrees authoritative** for candidate changes; remove copy-back apply behavior from autonomous paths and preserve additions/deletions through Git.
- [ ] **Step 6: Run focused tests** and expect lifecycle, crash recovery, locking, and complete tree semantics to pass.
- [ ] **Step 7: Commit** with `git commit -m "feat(update): add durable isolated candidate lifecycle"`.

### Task 6: Publish with compare-and-swap and recover Git failures

**Files:**
- Modify: `web_app/github_cli.py:320-537`
- Modify: `web_app/git_broker.py:236-259,302-317`
- Modify: `web_app/core/autonomous_update.py`
- Test: `test_github_cli.py`
- Test: `test_git_broker.py`
- Test: `test_autonomous_update.py`

**Interfaces:**
- Produces: `GitHubCLI.publish_verified(project_root, branch, commit_sha, expected_remote_sha) -> PublicationReceipt`.
- Produces: `GitHubCLI.reconcile_publication(branch, commit_sha) -> PublicationState`.

- [ ] **Step 1: Add failing tests** for remote drift, divergence, non-fast-forward rejection, ambiguous network success, duplicate retry, rebase conflict, merge conflict, and concurrent process attempts.
- [ ] **Step 2: Run** `C:\Python315\python.exe -m unittest test_github_cli.py test_git_broker.py test_autonomous_update.py`; expect direct push/rebase paths to lack recovery.
- [ ] **Step 3: Implement compare-and-swap publication** using the observed remote SHA and exact verified commit; never force push.
- [ ] **Step 4: Reconcile ambiguous results** by querying the remote commit before retrying; persist one receipt per candidate/commit.
- [ ] **Step 5: Run rebase/merge only in candidate worktrees** and execute explicit abort handlers on failure before releasing the repository lock.
- [ ] **Step 6: Run focused tests** and expect remote drift, ambiguity, retries, and conflicts to finish in deterministic states.
- [ ] **Step 7: Commit** with `git commit -m "fix(git): make verified publication recoverable"`.

### Task 7: Add stable launcher, candidate health, activation, and rollback

**Files:**
- Create: `web_app/core/update_launcher.py`
- Create: `json_codr_launcher.py`
- Modify: `run_web.ps1`
- Modify: `web_app/app.py`
- Modify: `web_app/core/autonomous_update.py`
- Test: `test_update_launcher.py`
- Test: `test_run_web.py`
- Test: `test_autonomous_update.py`

**Interfaces:**
- Produces: `ActiveBuildPointer(revision, root, version, activated_at, previous_revision)` stored atomically outside candidate roots.
- Produces: `UpdateLauncher.launch_candidate(candidate, profile) -> HealthReceipt`, `activate(receipt) -> ActivationReceipt`, and `rollback(activation_id) -> RollbackReceipt`.

- [ ] **Step 1: Add failing tests** for candidate version mismatch, unavailable port, startup failure, API failure, fatal browser error receipt, incompatible migration, pointer-write interruption, post-switch failure, and successful automatic rollback.
- [ ] **Step 2: Run** `C:\Python315\python.exe -m unittest test_update_launcher.py test_run_web.py test_autonomous_update.py`; expect launcher interfaces to be absent.
- [ ] **Step 3: Implement atomic active-build pointers** and a minimal stable launcher that owns the child process and never imports candidate application code.
- [ ] **Step 4: Launch candidates on dynamic loopback ports** with disposable data roots and exact commit/version environment; collect bounded health evidence.
- [ ] **Step 5: Block irreversible migrations** and require backward compatibility for unattended activation.
- [ ] **Step 6: Activate only healthy receipts** and automatically switch back to the previous pointer when post-activation health fails.
- [ ] **Step 7: Run focused tests** and expect startup, migration, pointer, activation, and rollback cases to pass.
- [ ] **Step 8: Commit** with `git commit -m "feat(update): activate verified builds with rollback"`.

### Task 8: Administrator controls, compatibility migration, and end-to-end proof

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/source-control.html`
- Modify: `web_app/app.py`
- Modify: `README.md`
- Modify: `web_app/version.py`
- Modify: `run_web.ps1`
- Test: `test_web_static.py`
- Test: `test_identity_api.py`
- Test: `test_autonomous_update.py`
- Test: `test_version.py`

**Interfaces:**
- Adds Administrator views for update profile, candidates, checks, manifests, publication receipts, active/previous build, quarantine, activation, and rollback.
- Exposes read-only candidate status to ordinary authenticated users; all mutation controls use server-provided permission state.

- [ ] **Step 1: Add failing API/static tests** for permission-derived controls, disabled automatic mode before prerequisites, route inventory completeness, legacy mutation-header rejection, quarantine, and reverse actions.
- [ ] **Step 2: Run** `C:\Python315\python.exe -m unittest test_web_static.py test_identity_api.py test_autonomous_update.py test_version.py`; expect missing controls and migration enforcement.
- [ ] **Step 3: Add thin HTTP routes and UI controls** backed only by `AutonomousUpdateController`; do not implement Git, filesystem, launch, or policy logic in handlers or JavaScript.
- [ ] **Step 4: Generate and assert the mutation-route inventory** so future write endpoints fail tests until assigned an authenticated scope.
- [ ] **Step 5: Run the complete focused regression set** for identity, policy, native primitives, command runtime, GitHub, broker, coding agents, task store, launcher, settings, static web, launcher script, and version; expect all tests to pass.
- [ ] **Step 6: Start the current and candidate builds on separate ports**; use the in-app browser to verify Administrator controls, candidate evidence, no fatal console errors, successful activation, and rollback to the prior build.
- [ ] **Step 7: Increment the release version** only after the end-to-end proof succeeds and update concise user documentation.
- [ ] **Step 8: Commit** with `git commit -m "feat(update): release verified autonomous self-update"`.

## Final verification

- [ ] Run `git diff --check` and `node --check web/app.js`.
- [ ] Run every focused test file changed by Tasks 1-8; no repo-wide test command.
- [ ] Confirm no mutation endpoint accepts `X-JSON-CODR: 1` as authority.
- [ ] Confirm a spoofed capability operation cannot change its risk.
- [ ] Confirm automatic mode cannot execute raw shell commands.
- [ ] Confirm edit-after-verify invalidates publication.
- [ ] Confirm candidate failure leaves the current build serving requests.
- [ ] Confirm post-activation failure automatically restores the previous build.
- [ ] Confirm local and remote Git revisions match after approved publication.
