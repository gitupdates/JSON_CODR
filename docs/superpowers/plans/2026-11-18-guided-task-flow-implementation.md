# Guided Task Flow V1.0.18-alpha.12 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Use `superpowers:test-driven-development` for every behavior change and `superpowers:verification-before-completion` before claiming completion.

**Goal:** Replace the live one-shot workspace route with a durable Describe → Plan → Execute → Deliver task flow whose plan and steps can be reviewed, edited, revised, approved, or rejected under exact-digest policy controls.

**Architecture:** Extend the immutable core contracts and append-only `TaskStore` first, then add policy snapshots and a plan-review service, refactor `AgentRuntime` to execute approved plan revisions, expose the behavior through core and compatibility APIs, and finally project the durable state into the NOC Light UI. Existing MCP `stdio` tools remain supported through a connector-safe step contract; remote transports and OAuth remain alpha.13 work.

**Tech stack:** Python 3.12 core runtime, Pydantic contracts, SQLite persistence, FastAPI, vanilla JavaScript/CSS, `unittest`/pytest-compatible tests.

---

## Task 1: Extend immutable plan contracts

**Files:**

- Modify: `web_app/core/contracts.py`
- Modify: `test_goal_contracts.py`
- Create: `test_plan_contracts.py`

**Step 1: Write failing contract tests**

Add tests proving:

- `PlanRevision` stores summary, deliverables, author, parent revision, reason, review status, and canonical digest;
- `PlannedStep` stores title, purpose, dependencies, target, effect class, evidence expectations, review status, and digest;
- `PlannedStep` optionally records provider-neutral skill, Skillset, plugin, command, and agent-profile provenance without treating it as authority;
- connector metadata stores identifiers and digests but rejects token/secret fields;
- duplicate IDs, missing dependencies, dependency cycles, cross-plan steps, and mismatched digests fail validation;
- approved revisions are frozen;
- canonical serialization produces a stable digest.

Run: `python -m unittest test_plan_contracts.py test_goal_contracts.py -v`

Expected: FAIL because the new fields and validators do not exist.

**Step 2: Implement the minimum contract types**

Add enums for task phase, plan/step review status, revision author, effect class, and step disposition. Add a bounded `ConnectorStepMetadata` contract. Extend `PlannedStep` and `PlanRevision` while preserving schema-version parsing for existing records. Compute digests through `web_app/core/canonical.py`; never accept user-supplied secrets.

Add an immutable origin-reference contract whose identifiers and content digests are included in the step digest. Origin data must not alter policy decisions or imply permission.

**Step 3: Run the focused tests**

Run: `python -m unittest test_plan_contracts.py test_goal_contracts.py -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add web_app/core/contracts.py test_goal_contracts.py test_plan_contracts.py
git commit -m "feat(core): add reviewable plan contracts"
```

## Task 2: Persist revisions, decisions, and derived phase

**Files:**

- Modify: `web_app/core/store.py`
- Modify: `test_core_store.py`
- Create: `test_plan_store.py`

**Step 1: Write failing persistence tests**

Cover revision append/read, immutable approved revisions, optimistic expected-digest checks, idempotent duplicate decisions, rejection finality for one digest, completed-step carry-forward, phase derivation from events, and reconstruction after closing/reopening SQLite.

Run: `python -m unittest test_plan_store.py test_core_store.py -v`

Expected: FAIL because plan persistence APIs do not exist.

**Step 2: Add normalized persistence and append-only events**

Add migrations/tables for plan revisions and review decisions keyed by task, plan, revision, and step. Store canonical JSON and digest. Keep phase authoritative in events and expose a deterministic projection method. Reject in-place updates.

**Step 3: Run focused tests**

Run: `python -m unittest test_plan_store.py test_core_store.py -v`

Expected: PASS, including reopen recovery.

**Step 4: Commit**

```powershell
git add web_app/core/store.py test_core_store.py test_plan_store.py
git commit -m "feat(core): persist plan review history"
```

## Task 3: Add execution-policy snapshots and settings migration

**Files:**

- Modify: `web_app/core/policy.py`
- Modify: `web_app/models.py`
- Modify: `web_app/settings.py`
- Modify: `web_app/workspace.py`
- Modify: `test_core_service.py`
- Modify: `test_settings.py`
- Create: `test_execution_policy.py`

**Step 1: Write failing policy tests**

Test the complete effect table for Balanced, Strict, and Autonomous. Assert that all presets require plan-structure approval; Autonomous only removes additional prompts for `allow` steps. Test override precedence, immutable snapshots, hard destructive confirmation, unknown connector effects defaulting to `ask`, and schema-2-to-schema-3 migration without broadened grants.

Run: `python -m unittest test_execution_policy.py test_settings.py test_core_service.py -v`

Expected: FAIL because presets, snapshots, and schema 3 do not exist.

**Step 2: Implement policy contracts and migration**

Represent decisions as `allow`, `ask`, `deny`, or `strong_confirm`; add preset/effect tables and advanced global/project overrides. Store a canonical policy snapshot digest on task creation. Preserve current project-containment and brokered-boundary denials ahead of every override.

**Step 3: Run focused tests**

Run: `python -m unittest test_execution_policy.py test_settings.py test_core_service.py -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add web_app/core/policy.py web_app/models.py web_app/settings.py web_app/workspace.py test_core_service.py test_settings.py test_execution_policy.py
git commit -m "feat(policy): add task execution presets and snapshots"
```

## Task 4: Build plan review and revision service

**Files:**

- Create: `web_app/core/plan_service.py`
- Create: `test_plan_service.py`
- Modify: `web_app/core/capabilities.py`

**Step 1: Write failing service tests**

Test whole-plan and step approve/reject/edit/revise operations, exact-digest requirements, bounded editable fields, transitive invalidation, unchanged independent approval retention, rejection recovery only through a newer revision, capability/schema validation, and one-step/one-call enforcement.

Run: `python -m unittest test_plan_service.py -v`

Expected: FAIL because `PlanService` does not exist.

**Step 2: Implement `PlanService`**

Make it the only writer for plan review operations. Accept structured edits, recalculate server-owned effect/digest fields, resolve capability schemas from the registry, append events, and return conflict objects carrying the current revision/digest.

**Step 3: Run focused tests**

Run: `python -m unittest test_plan_service.py -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add web_app/core/plan_service.py web_app/core/capabilities.py test_plan_service.py
git commit -m "feat(core): add plan review service"
```

## Task 5: Make existing MCP calls connector-safe

**Files:**

- Modify: `web_app/core/mcp_stdio_backend.py`
- Modify: `web_app/core/mcp_adapter.py`
- Modify: `web_app/core/adapters.py`
- Modify: `test_mcp_stdio_backend.py`
- Create: `test_mcp_plan_safety.py`

**Step 1: Write failing MCP safety tests**

Assert that discovery returns stable server/tool/schema identities, connector calls expose no configured secrets, changed tool schemas invalidate a planned digest, unknown annotations remain `ask`, remote mutations classify as `external_effect`, and interrupted calls are never automatically replayed.

Run: `python -m unittest test_mcp_stdio_backend.py test_mcp_plan_safety.py -v`

Expected: FAIL because connector-safe metadata is not produced.

**Step 2: Add metadata without expanding transport scope**

Retain `stdio` only. Normalize tool schemas and annotations, expose their digests to planning, redact environment/configuration secrets, and pass connector provenance through adapter events. Do not add HTTP or OAuth in alpha.12.

**Step 3: Run focused tests**

Run: `python -m unittest test_mcp_stdio_backend.py test_mcp_plan_safety.py -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add web_app/core/mcp_stdio_backend.py web_app/core/mcp_adapter.py web_app/core/adapters.py test_mcp_stdio_backend.py test_mcp_plan_safety.py
git commit -m "feat(mcp): bind tool calls to safe plan metadata"
```

## Task 6: Refactor `AgentRuntime` around reviewed revisions

**Files:**

- Modify: `web_app/core/agent_runtime.py`
- Modify: `web_app/core/service.py`
- Modify: `test_agent_runtime.py`
- Create: `test_guided_runtime.py`

**Step 1: Write failing runtime tests**

Cover:

- planning emits a complete revision and pauses in `plan_review` before effects for every preset;
- read-only planning does not dispatch connector calls;
- approved exact steps execute sequentially as child tasks;
- altered arguments, policy, schema, or fingerprint return to review;
- carried-forward completed steps never replay;
- interrupted external effects require an explicit retry decision;
- Strict pauses before every call after plan approval;
- Autonomous executes only `allow` steps after plan approval;
- unplanned actions require a new revision;
- verification and delivery happen only after all approved steps resolve.

Run: `python -m unittest test_agent_runtime.py test_guided_runtime.py -v`

Expected: FAIL against the current call-at-a-time planner loop.

**Step 2: Implement the revision-driven state machine**

Split planning from execution. Have the planner return `PlanRevision`; persist it; pause for review; dispatch ready approved steps; bind child IDs to revision and step digest; and derive phase transitions from events. Keep repair limits and verification evidence checks.

**Step 3: Run focused tests**

Run: `python -m unittest test_agent_runtime.py test_guided_runtime.py -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add web_app/core/agent_runtime.py web_app/core/service.py test_agent_runtime.py test_guided_runtime.py
git commit -m "feat(agent): execute approved plan revisions"
```

## Task 7: Add policy apply and baseline refresh recovery

**Files:**

- Modify: `web_app/core/project_adapter.py`
- Modify: `web_app/core/plan_service.py`
- Modify: `web_app/core/agent_runtime.py`
- Create: `test_task_recovery.py`

**Step 1: Write failing recovery tests**

Test canonical project fingerprints, paused-only policy application, pending-approval invalidation, baseline refresh revisions, completed-step ancestry rules, HTTP-conflict-worthy invalid states, and no guessing when ancestry cannot be proved.

Run: `python -m unittest test_task_recovery.py test_core_project_runtime.py -v`

Expected: FAIL.

**Step 2: Implement recovery operations**

Use `ProjectAdapter.snapshot()` as the authoritative fingerprint. Append policy/baseline events and create new revisions through `PlanService`; never mutate the old revision.

**Step 3: Run focused tests**

Run: `python -m unittest test_task_recovery.py test_core_project_runtime.py -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add web_app/core/project_adapter.py web_app/core/plan_service.py web_app/core/agent_runtime.py test_task_recovery.py
git commit -m "feat(agent): add safe policy and baseline recovery"
```

## Task 8: Expose plan and recovery APIs

**Files:**

- Modify: `web_app/core/api.py`
- Modify: `web_app/app.py`
- Modify: `web_app/models.py`
- Modify: `test_core_api.py`
- Modify: `test_web_api.py`
- Create: `test_plan_api.py`

**Step 1: Write failing API tests**

Test all plan/step approve, reject, edit, and revise endpoints; `expected_plan_digest`; RFC 9457-style validation details; 404/409 behavior; policy apply; baseline refresh; and secret redaction. Test `/api/workspace/tasks` returning HTTP 202 with durable task identity and never calling `execute_project_workspace()` when the feature flag is enabled.

Run: `python -m unittest test_plan_api.py test_core_api.py test_web_api.py -v`

Expected: FAIL.

**Step 2: Implement API models and routes**

Inject `PlanService` into the router. Preserve the legacy response fields while adding task phase, plan revision, event URL, policy disclosure, and artifact references. Keep the old one-shot function only behind the temporary diagnostic fallback.

**Step 3: Run focused tests**

Run: `python -m unittest test_plan_api.py test_core_api.py test_web_api.py -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add web_app/core/api.py web_app/app.py web_app/models.py test_core_api.py test_web_api.py test_plan_api.py
git commit -m "feat(api): expose guided plan workflow"
```

## Task 9: Populate verification delivery and artifacts

**Files:**

- Modify: `web_app/core/agent_verification.py`
- Modify: `web_app/core/artifact_store.py`
- Modify: `web_app/core/agent_runtime.py`
- Modify: `web_app/models.py`
- Modify: `test_agent_verification.py`
- Modify: `test_artifacts.py`
- Create: `test_task_delivery.py`

**Step 1: Write failing delivery tests**

Assert delivery includes executed revision, route disclosure, changed paths, child results, verification evidence, warnings, recovery controls, and authorized artifact references. Assert failed artifact writes are reported and no filesystem path leaks into API output.

Run: `python -m unittest test_task_delivery.py test_agent_verification.py test_artifacts.py -v`

Expected: FAIL.

**Step 2: Implement delivery projection**

Build delivery from durable events and `ArtifactStore`, not planner prose. Keep verification based on fresh evidence/fingerprint and publish only task-scoped download identifiers.

**Step 3: Run focused tests**

Run: `python -m unittest test_task_delivery.py test_agent_verification.py test_artifacts.py -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add web_app/core/agent_verification.py web_app/core/artifact_store.py web_app/core/agent_runtime.py web_app/models.py test_agent_verification.py test_artifacts.py test_task_delivery.py
git commit -m "feat(agent): deliver verified task results"
```

## Task 10: Implement the four-phase web interface

**Files:**

- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/task_view.js`
- Modify: `web/core_client.js`
- Modify: `web/app.css`
- Modify: `web/gamma.css`
- Modify: `test_web_static.py`
- Modify: `test_ui_customization.py`
- Create: `test_guided_task_ui.py`

**Step 1: Write failing static/UI tests**

Test visible Describe/Plan/Execute/Deliver phase controls, activated Plan/Changes/Results panels, whole-plan and step actions, structured editors, revision history, effect/policy labels, artifact download cards, header collapse persistence, keyboard labels, focus targets, `aria-live`, reduced motion, and narrow viewport classes.

Run: `python -m unittest test_guided_task_ui.py test_web_static.py test_ui_customization.py -v`

Expected: FAIL because the existing tabs are hidden and review controls do not exist.

**Step 2: Implement durable-state rendering**

Render phase and review state from task events/API responses. Wire approve/reject/edit/revise with expected digests and conflict refresh. Keep NOC Light as the selected appearance while preserving later theme changes and collapsible headers.

**Step 3: Run focused tests**

Run: `python -m unittest test_guided_task_ui.py test_web_static.py test_ui_customization.py -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add web/index.html web/app.js web/task_view.js web/core_client.js web/app.css web/gamma.css test_web_static.py test_ui_customization.py test_guided_task_ui.py
git commit -m "feat(ui): add guided task review workflow"
```

## Task 11: Add end-to-end compatibility and recovery coverage

**Files:**

- Modify: `test_workspace.py`
- Modify: `test_core_architecture.py`
- Modify: `test_core_web.py`
- Create: `test_guided_task_e2e.py`

**Step 1: Write end-to-end tests**

Exercise a complete Balanced task through describe, plan approval, edit execution, verification, delivery, refresh/reconstruction, artifact download, and undo. Add Strict and Autonomous smoke paths, an MCP read/write gating path, browser disconnect behavior, server restart during an effect, stale project recovery, and legacy-response parsing.

Run: `python -m unittest test_guided_task_e2e.py test_workspace.py test_core_architecture.py test_core_web.py -v`

Expected: PASS only when all integration wiring is complete.

**Step 2: Remove compatibility defects only**

Fix defects exposed by the test without broadening scope. Keep the legacy diagnostic fallback behind `guided_task_flow`; do not add alpha.13 transports or OAuth.

**Step 3: Run the entire suite**

Run: `python -m unittest discover -v`

Expected: PASS.

**Step 4: Commit**

```powershell
git add test_guided_task_e2e.py test_workspace.py test_core_architecture.py test_core_web.py
git commit -m "test: verify guided task flow end to end"
```

## Task 12: Version, documentation, and release verification

**Files:**

- Modify: `web_app/version.py`
- Modify: `README.md`
- Modify: `docs/user/provider-compatibility.md`
- Modify: `test_version.py`
- Modify: `docs/superpowers/specs/2026-11-18-guided-task-flow-design.md`

**Step 1: Update release identity and documentation**

Set `V1.0.18-alpha.12`, document the supported Python runtime split, guided policy presets, plan/step controls, current `stdio` MCP boundary, provider-neutral skill/plugin provenance boundary, and alpha.13 connector/plugin roadmap. Mark the approved design implemented only after verification succeeds.

**Step 2: Run release checks**

Run:

```powershell
python -m unittest discover -v
python -m compileall -q web_app
git diff --check
git status --short
```

Expected: all tests pass, compilation succeeds, no whitespace errors, and status contains only intended alpha.12 files.

**Step 3: Perform a local smoke test**

Start with the documented Python 3.12 command on a free port, confirm `/api/health`, create a read-only task, approve its plan, and verify the delivered result in NOC Light. Stop the server cleanly.

**Step 4: Commit**

```powershell
git add web_app/version.py README.md docs/user/provider-compatibility.md test_version.py docs/superpowers/specs/2026-11-18-guided-task-flow-design.md
git commit -m "release: prepare V1.0.18-alpha.12"
```

## Final verification gate

Before publishing or merging:

1. Invoke `superpowers:requesting-code-review` for an independent review against the approved design.
2. Resolve review findings using `superpowers:receiving-code-review`.
3. Invoke `superpowers:verification-before-completion` and rerun the full release checks from a clean process.
4. Use `superpowers:finishing-a-development-branch` to decide whether to merge, push the branch, or open a pull request.
5. Do not publish alpha.12 if any plan approval can authorize changed arguments, any interrupted effect can replay automatically, any secret appears in durable/frontend state, or the live workspace still bypasses the reviewed runtime.
