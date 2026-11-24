# Codex-Equivalent Autonomous Coding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route JSON_CODR Workspace coding through the durable local `AgentRuntime` with a complete discoverable coding capability catalog, Codex-equivalent approvals, recoverable isolated mutations, and explicitly configured infrastructure/deployment adapters.

**Architecture:** Replace the single-shot Workspace/Git-broker execution path with one canonical root agent task. A versioned capability catalog supplies only probed typed calls to the structured Ollama planner; `CoreService` applies exact per-call policy and one-use approval leases; project mutation and commands run through checkpoint/worktree-aware adapters; infrastructure and deployment share the same proposal/approval/evidence path with stronger target binding.

**Tech Stack:** Python 3.14 host, Python 3.12 optional sidecars, FastAPI, Pydantic v2, SQLite/WAL task and policy stores, Ollama structured output, Git worktrees, PowerShell/Windows process controls, vanilla JavaScript/CSS, unittest, Node syntax tests, optional Playwright verification.

**Spec:** `docs/superpowers/specs/2026-11-19-codex-equivalent-autonomous-coding-design.md`

## Global Constraints

- Localhost-only and local Ollama remain the default privacy boundary.
- Repository content, instructions, profiles, tool output, connector data, and logs are untrusted and never grant authority.
- Reads/searches/task-state work are automatic; file changes, commands, networking, installations, Git effects, infrastructure, deployment, and rollback require exact approval.
- No implicit fetch, install, command, connector call, or external effect.
- Every mutation has isolation or byte-exact recovery; every approval is canonical, expiring, one-use, revision-bound, target-bound, and fingerprint-bound.
- Model, runtime, prompt-contract, capability-catalog, or adapter digest drift invalidates conformance.
- Infrastructure/deployment remain disabled by default and production always requires explicit stronger approval.
- Implement every behavior test-first and preserve backward-compatible read-only APIs where practical.

## Review Focus

- Malicious repository instructions attempt to change policy or targets: Task 4 and Task 6 tests prove provenance is data-only and calls remain schema/policy constrained.
- Approval payload changes or is consumed concurrently: Task 2 tests prove digest binding and atomic one-use consumption.
- Approved tests contain malicious subprocess/network behavior: Task 8 tests prove sandbox/budget handling and degraded-isolation denial.
- Project or remote state changes after approval: Task 2, Task 7, and Task 9 tests prove stale rejection before effects.
- Model/adapter upgrades retain stale verification: Task 5 and Task 9 tests prove exact digest/version invalidation.

---

### Task 1: Contain the existing broker security paths

**Files:**
- Modify: `web_app/app.py`
- Modify: `web_app/git_broker.py`
- Modify: `web_app/coding_agents.py`
- Test: `test_git_broker.py`
- Test: `test_web_api.py`

**Interfaces:**
- Consumes: existing `GitBrokerService.execute(...)`, `CodingAgentService.grant(...)`, and `execute_git_through_core(...)`.
- Produces: local-only broker execution with no implicit fetch and no automatically minted sensitive policy grant; deprecated single-shot endpoint rejects sensitive actions.

- [ ] **Step 1: Write failing tests** proving status/read/apply-patch never call `git fetch`, commit/sync/push remain permission-required, and `/api/project-workspace/run` cannot mint a full broker grant or execute sensitive actions.
- [ ] **Step 2: Run the focused tests and confirm RED** because the current broker fetches upstreams and `execute_git_through_core` grants sensitive operations.
- [ ] **Step 3: Remove unconditional fetch and automatic `core_policy.grant`; restrict compatibility execution to local read/status proposals and return approval-required for every effect.**
- [ ] **Step 4: Run `python -m unittest test_git_broker.py test_web_api.py -v` and confirm the new security tests pass.**
- [ ] **Step 5: Commit** with `fix(security): contain legacy broker effects`.

### Task 2: Exact one-use approval leases

**Files:**
- Create: `web_app/core/approval.py`
- Modify: `web_app/core/contracts.py`
- Modify: `web_app/core/policy.py`
- Modify: `web_app/core/service.py`
- Modify: `web_app/core/api.py`
- Test: `test_core_approval.py`
- Test: `test_core_service.py`

**Interfaces:**
- Consumes: `CapabilityCall`, canonical digesting, task/step events, and project fingerprints.
- Produces: `ApprovalProposal`, `ApprovalLease`, `ApprovalStore.propose(...)`, `ApprovalStore.consume(...)`, and `CoreService.approve_exact(...)`.

- [ ] **Step 1: Write failing contract/store tests** for canonical call digest, principal/project/task/step revision, fingerprint, target, expiry, one-use state, atomic concurrent consumption, rejection, revocation, and stale invalidation.
- [ ] **Step 2: Run the focused tests and confirm RED** because exact approval records do not exist.
- [ ] **Step 3: Implement SQLite-backed approval proposals and leases** with WAL, unique consumption transition, hash-linked identifiers, and no stored credentials.
- [ ] **Step 4: Write failing service/API tests** proving approval requires the exact proposal digest and that edits, repairs, revisions, restarts of ephemeral authority, expiry, and fingerprint changes reject execution.
- [ ] **Step 5: Run the service/API tests and confirm RED**, then replace broad `PolicyService.grant` approval with exact lease consumption while retaining explicitly user-created narrow project rules.
- [ ] **Step 6: Run `python -m unittest test_core_approval.py test_core_service.py test_core_api.py -v` and confirm GREEN.**
- [ ] **Step 7: Commit** with `feat(core): add exact one-use approvals`.

### Task 3: Durable project registration and trusted context boundaries

**Files:**
- Create: `web_app/core/project_registry.py`
- Modify: `web_app/core/agent_services.py`
- Modify: `web_app/core/project_intelligence.py`
- Modify: `web_app/core/context_service.py`
- Modify: `web_app/app.py`
- Test: `test_core_project_registry.py`
- Test: `test_project_intelligence.py`
- Test: `test_agent_services.py`

**Interfaces:**
- Consumes: selected project root and `ProjectReader`.
- Produces: `ProjectRegistry.register(root)`, `ProjectRegistry.resolve(project_id)`, durable project metadata, provenance-labeled `ContextSource`, and bounded secret-aware snapshots.

- [ ] **Step 1: Write failing tests** for stable project IDs, missing/unregistered projects, root/symlink/reparse escape, changed roots, restart persistence, and per-project lookup.
- [ ] **Step 2: Run tests and confirm RED**, then implement the registry with atomic metadata and resolved-root fingerprints.
- [ ] **Step 3: Write failing context tests** proving `AGENTS.md` is labeled untrusted project instruction, known secret/private-key/environment/cloud-profile files are excluded, binary/oversized files are omitted with evidence, and project text cannot alter policy fields.
- [ ] **Step 4: Run tests and confirm RED**, then implement provenance, exclusions, byte limits, and omission records.
- [ ] **Step 5: Replace the hard-coded `legacy` resolver with the registry and run `python -m unittest test_core_project_registry.py test_project_intelligence.py test_agent_services.py test_context_service.py -v`.**
- [ ] **Step 6: Commit** with `feat(core): register durable project context`.

### Task 4: Versioned coding capability catalog

**Files:**
- Create: `web_app/core/capability_catalog.py`
- Create: `web_app/core/capability_discovery.py`
- Modify: `web_app/core/adapters.py`
- Modify: `web_app/core/api.py`
- Modify: `web_app/app.py`
- Test: `test_capability_catalog.py`
- Test: `test_capability_discovery.py`

**Interfaces:**
- Produces: `CapabilityDefinition`, `CapabilityAvailability`, `CapabilityCatalog.list_for_project(...)`, `CapabilityCatalog.planner_schema(...)`, and deterministic project profile discovery.
- Catalog entries declare schemas, effect class, approval class, prerequisites, supported project types, verification, rollback class, adapter and version digests.

- [ ] **Step 1: Write failing catalog tests** for unique stable IDs, frozen schemas, digest stability, policy visibility, unavailable prerequisite reasons, and exclusion of unprobed adapters.
- [ ] **Step 2: Run and confirm RED**, then implement catalog contracts and registry.
- [ ] **Step 3: Write failing discovery tests** for Python, Node, .NET, Java, Go, Rust, containers, browser tests, databases, Terraform/Bicep/CloudFormation/Kubernetes/Helm, while treating repo-defined profiles as untrusted pending review.
- [ ] **Step 4: Run and confirm RED**, then implement manifest-only discovery without executing project code.
- [ ] **Step 5: Seed typed lifecycle definitions** for read/search/file operations, refactor/debug/docs/review, named build/test/lint/format/type-check/package/benchmark/run, dependency/license/vulnerability work, Git/worktrees, services/databases/containers/browser/API/desktop/MCP/LSP/debugger/profiler, infrastructure preview/apply, deployment/health/log/rollback.
- [ ] **Step 6: Run `python -m unittest test_capability_catalog.py test_capability_discovery.py test_core_api.py -v`.**
- [ ] **Step 7: Commit** with `feat(core): add coding capability catalog`.

### Task 5: Structured local-model planner and conformance evidence

**Files:**
- Create: `web_app/core/model_conformance.py`
- Modify: `web_app/core/agent_services.py`
- Modify: `web_app/core/native_ollama.py`
- Modify: `web_app/ollama_service.py`
- Modify: `web_app/settings.py`
- Modify: `web_app/models.py`
- Test: `test_agent_services.py`
- Test: `test_model_conformance.py`
- Test: `test_core_native_ollama.py`

**Interfaces:**
- Consumes: `CapabilityCatalog.planner_schema(...)` and local Ollama JSON schema support.
- Produces: strict `InferencePlanner` structured calls, `ModelConformanceRecord`, classifications `native_verified`, `broker_verified`, `chat_only`, and evidence-backed route selection.

- [ ] **Step 1: Write failing parser tests** rejecting prose, multiple fences/objects, duplicate keys, unknown fields, oversized output, invalid capability/operation/arguments, project-root injection, and `done` without evidence.
- [ ] **Step 2: Run and confirm RED**, then implement direct schema generation plus only exact whitespace/single-fence compatibility normalization.
- [ ] **Step 3: Write failing conformance tests** binding model digest, Ollama/runtime version, planner contract version, catalog digest, adapter digests, result evidence, and invalidation on any drift.
- [ ] **Step 4: Run and confirm RED**, then implement persisted conformance records and installed-model checks; remove static claims that an unavailable fallback is usable.
- [ ] **Step 5: Add a disposable-project Qwen 7B conformance harness** gated as a real-model integration test; it must not receive credentials or network authority.
- [ ] **Step 6: Run focused unit tests and the real-model harness; classify Qwen as broker-verified only if the exact installed digest passes.**
- [ ] **Step 7: Commit** with `feat(inference): verify structured coding models`.

### Task 6: Canonical Workspace-to-AgentRuntime flow

**Files:**
- Modify: `web_app/app.py`
- Modify: `web_app/models.py`
- Modify: `web_app/core/agent_runtime.py`
- Modify: `web_app/core/agent_services.py`
- Modify: `web_app/core/context_service.py`
- Test: `test_workspace_agent_e2e.py`
- Test: `test_agent_runtime.py`
- Test: `test_web_api.py`

**Interfaces:**
- Consumes: project registry, capability catalog, structured planner, approval store, `GoalSpec`, and core task APIs.
- Produces: `POST /api/workspace/tasks` durable `agent.run` creation with real project ID, requested/effective model route, task ID, and running/approval-required/completed states.

- [ ] **Step 1: Write a failing E2E test** in which the planner must read a file, receive its content in the next turn, propose an edit, pause for approval, apply it, request an approved verification profile, and complete only with fresh evidence.
- [ ] **Step 2: Run and confirm RED** because Workspace currently uses single-shot broker execution.
- [ ] **Step 3: Create the accepted goal/root task in Workspace and route it through `AgentRuntime`; remove the canonical UI's dependency on `execute_project_workspace`.**
- [ ] **Step 4: Extend planner context with catalog, current plan revision, child results, failures, steering, omissions, and provenance while keeping budgets bounded.**
- [ ] **Step 5: Run the E2E and runtime/API suites and confirm iterative behavior, restart reconciliation, cancellation, repeated-failure blocking, and no mutation before approval.**
- [ ] **Step 6: Commit** with `feat(workspace): use canonical coding agent runtime`.

### Task 7: Plan and step revision controls

**Files:**
- Modify: `web_app/core/contracts.py`
- Modify: `web_app/core/store.py`
- Modify: `web_app/core/service.py`
- Modify: `web_app/core/api.py`
- Modify: `web_app/core/agent_runtime.py`
- Test: `test_plan_revisions.py`
- Test: `test_agent_runtime.py`

**Interfaces:**
- Produces: durable `PlanRevision`, whole-plan approve/reject/edit/revise, step approve/reject/edit/revise, dependency invalidation, and revision-aware approval/evidence checks.

- [ ] **Step 1: Write failing store/contract tests** for ordered steps, stable IDs, revision increments, dependency validation, optimistic concurrency, and immutable history.
- [ ] **Step 2: Run and confirm RED**, then persist complete plan revisions rather than only step reservations.
- [ ] **Step 3: Write failing API/runtime tests** for whole-plan and single-step direct edits, model revision requests, rejection, dependent-step invalidation, old approval rejection, and stale evidence rejection.
- [ ] **Step 4: Run and confirm RED**, then implement revision events and runtime resume semantics.
- [ ] **Step 5: Run `python -m unittest test_plan_revisions.py test_agent_runtime.py test_core_api.py -v`.**
- [ ] **Step 6: Commit** with `feat(agent): add plan and step revision controls`.

### Task 8: Isolated mutations, constrained commands, and recovery

**Files:**
- Create: `web_app/core/worktree_runtime.py`
- Create: `web_app/core/command_runtime.py`
- Modify: `web_app/core/project_adapter.py`
- Modify: `web_app/core/native_primitives.py`
- Modify: `web_app/core/service.py`
- Test: `test_worktree_runtime.py`
- Test: `test_command_runtime.py`
- Test: `test_core_project_runtime.py`

**Interfaces:**
- Produces: per-project writer locks, managed isolated worktrees, patch/checkpoint records, exact undo, named-command execution with `CommandPolicy`, budgets, redaction, cancellation, and declared isolation level.

- [ ] **Step 1: Write failing worktree tests** for isolation, symlink/reparse rejection, dirty source repositories, concurrent writer rejection, fingerprint drift, failed verification containment, interruption reconciliation, exact apply-to-source approval, and undo of existing/new/deleted files.
- [ ] **Step 2: Run and confirm RED**, then implement managed worktrees and checkpoint fallback.
- [ ] **Step 3: Write failing command tests** for exact argv/cwd preview, sanitized environment, no shell interpolation, time/output/process budgets, cancellation, escape stripping, secret redaction, separate network approval, and denial when required isolation is unavailable.
- [ ] **Step 4: Run and confirm RED**, then implement platform-aware constrained execution; declare reduced isolation rather than claiming a sandbox that Windows cannot provide.
- [ ] **Step 5: Run `python -m unittest test_worktree_runtime.py test_command_runtime.py test_core_project_runtime.py test_core_native_primitives.py -v`.**
- [ ] **Step 6: Commit** with `feat(runtime): isolate coding effects and recovery`.

### Task 9: Infrastructure and deployment adapter framework

**Files:**
- Create: `web_app/core/external_effects.py`
- Create: `web_app/core/deployment.py`
- Modify: `web_app/core/capability_catalog.py`
- Modify: `web_app/core/policy.py`
- Modify: `web_app/core/service.py`
- Test: `test_external_effects.py`
- Test: `test_deployment.py`

**Interfaces:**
- Produces: `ExternalTarget`, `PreviewEvidence`, `RollbackClass`, `DeploymentAdapter` protocol, disabled-by-default adapter registry, opaque credential resolution boundary, preview/apply/health/rollback state machine.

- [ ] **Step 1: Write failing target tests** for account/subscription, region, cluster, namespace, service, environment, credential reference, remote fingerprint, and exact plan digest binding.
- [ ] **Step 2: Run and confirm RED**, then implement typed target/evidence contracts without real provider execution.
- [ ] **Step 3: Write failing state-machine tests** for disabled defaults, preview/apply separation, staging/production separation, stale preview rejection, credential redaction, health verification, rollback classes, stronger confirmation for unavailable rollback, and separately approved rollback.
- [ ] **Step 4: Run and confirm RED**, then implement the adapter protocol and fake/sandbox adapter used by conformance tests.
- [ ] **Step 5: Add discovery-only definitions for Terraform, Bicep, CloudFormation, Kubernetes, Helm, Docker/Compose, databases, and provider CLIs; availability requires a separately installed verified adapter.**
- [ ] **Step 6: Run `python -m unittest test_external_effects.py test_deployment.py test_capability_catalog.py -v`.**
- [ ] **Step 7: Commit** with `feat(deploy): add gated external effect adapters`.

### Task 10: Workspace plan, approval, capability, and recovery UI

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/app.css`
- Modify: `web/gamma.css`
- Test: `test_core_web.py`
- Test: `test_web_static.py`
- Test: `test_workspace_agent_client.py`

**Interfaces:**
- Consumes: task event stream, plan revisions, approval proposals, capability availability, checkpoints, evidence, and deployment target details.
- Produces: canonical plan/step review controls, direct edit/revise/reject/approve, exact effect review, isolation/rollback warnings, capability/prerequisite display, undo/recovery, and requested/effective model route labels.

- [ ] **Step 1: Write failing DOM/client tests** for plan and step controls, canonical fields separated from model prose, stale proposal handling, one-use approval, command/network/Git/deployment warnings, reduced-isolation blocking, checkpoint undo, steering, cancellation, restart resume, and unavailable capability explanations.
- [ ] **Step 2: Run Node/Python static tests and confirm RED.**
- [ ] **Step 3: Implement the minimum accessible UI and client state, preserving protected UI Designer IDs/regions and NOC Light themes.**
- [ ] **Step 4: Run `node --check web/app.js` and `python -m unittest test_core_web.py test_web_static.py test_workspace_agent_client.py -v`.**
- [ ] **Step 5: Commit** with `feat(ui): add autonomous coding review controls`.

### Task 11: Adversarial verification, migration, and rollout

**Files:**
- Create: `test_autonomous_coding_redteam.py`
- Create: `test_autonomous_coding_real_model.py`
- Modify: `web_app/settings.py`
- Modify: `web_app/models.py`
- Modify: `README.md`
- Modify: `CONTINUE_UI_DESIGNER.md`
- Modify: `docs/superpowers/specs/2026-11-19-codex-equivalent-autonomous-coding-redteam-review.md`

**Interfaces:**
- Produces: versioned `autonomous_coding` settings, non-migration of broad legacy grants, rollout flag, security/conformance report, and operator documentation.

- [ ] **Step 1: Write adversarial tests** covering every RT-01 through RT-15 finding, malicious repository instructions/output, approval spoofing/replay/concurrency, secret exfiltration, sandbox degradation, resource exhaustion, model/adapter drift, target confusion, and audit redaction.
- [ ] **Step 2: Run and confirm failures expose any remaining gaps; fix each through its owning component with a focused red-green cycle.**
- [ ] **Step 3: Add settings migration tests** proving autonomous coding is versioned, external adapters are disabled, and broad broker grants are archived rather than migrated.
- [ ] **Step 4: Run all focused Python and Node suites, then `python -m unittest discover -q`; record every failure by name and distinguish known environment failures only with evidence.**
- [ ] **Step 5: Run the real installed Qwen 7B disposable-project scenario:** read, plan, approval pause, edit in isolation, approved verification, approved apply, evidence completion, undo; prove no network or credentials were available.
- [ ] **Step 6: Perform the code-level Redteam review; release remains blocked until no critical/high finding remains. Update the review document with evidence and final decision.**
- [ ] **Step 7: Update README and continuation documentation with exact Python 3.14/3.12 launch, local-model conformance, approval behavior, and recovery commands.**
- [ ] **Step 8: Commit** with `feat(agent): deliver verified autonomous coding`.

## Final release verification

- [ ] `git diff --check` reports no errors.
- [ ] Focused security, runtime, Workspace, UI, deployment, and Designer suites pass.
- [ ] Full discovery results are recorded with zero new failures.
- [ ] Real Qwen 7B conformance passes against a disposable project.
- [ ] Local and remote branches contain the same reviewed commits after explicit publication approval.
