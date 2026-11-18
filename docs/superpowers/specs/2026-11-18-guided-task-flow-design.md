# Guided Task Flow V1.0.18-alpha.12 Design

## Intent

Turn the live JSON_CODR workspace into one durable, understandable workflow:

1. **Describe** — state the outcome, choose the project folder, attach context, and select an execution-policy preset.
2. **Plan** — let read-only discovery build a versioned plan, then review, edit, revise, approve, or reject the plan or any individual step.
3. **Execute** — run the exact approved revision through the existing capability, policy, checkpoint, and task-event infrastructure.
4. **Deliver** — verify the outcome and present changes, evidence, downloadable artifacts, and recovery controls together.

The purpose is not to imitate a four-card diagram. The purpose is to make the active product route use the durable orchestration components that already exist in `web_app/core`, so the interface truthfully represents what the system is doing.

## Goals

- Replace the one-shot `/api/workspace/tasks` execution path with a durable task driven by `AgentRuntime`, `TaskStore`, `CoreService`, and `PolicyService`.
- Make Describe, Plan, Execute, and Deliver visible, navigable phases of the same task.
- Make the full plan and each plan step independently reviewable.
- Support direct editing, model-assisted revision, approval, and rejection at both plan and step scope.
- Default to a practical Balanced policy: read-only discovery is automatic; effects pause for approval.
- Add Strict and Autonomous presets plus advanced per-capability overrides.
- Bind every approval to an exact task, project, plan revision, step digest, capability, arguments, and effect scope.
- Preserve project-root containment, checkpoints, cancellation, retry, steering, undo, model-route disclosure, and existing terminal safety.
- Populate task-owned artifact references and a useful delivery summary.
- Establish connector-safe planning, approval, provenance, and audit contracts that alpha.13 can use without weakening alpha.12 policy guarantees.
- Record the originating skill, Skillset, plugin, command, or agent profile on planned steps when present, without allowing that provenance to grant authority.
- Preserve the current `/api/workspace/tasks` client contract as a compatibility facade while moving its implementation onto the core runtime.
- Meet keyboard, focus, screen-reader, reduced-motion, and narrow-screen behavior already established by the Gamma UI.

## Non-goals

- Parallel execution of independent child steps. The alpha.12 runtime remains sequential; production delegation is a later revision.
- Production schedule creation or recovery UI. `ScheduleService` wiring is a later revision.
- Native Word, Excel, PowerPoint, PDF, research, spreadsheet-analysis, or batch file-management capabilities. Alpha.12 prepares their orchestration and artifact contracts but does not add them.
- Full MCP/connector parity: Streamable HTTP, OAuth, local/project/user configuration scopes, resources, prompts, elicitation, connector administration, and a connector catalog are deferred to alpha.13. Existing approved MCP `stdio` configuration remains the alpha.12 connector source.
- Organization-wide identity, tenant administration, or hosted proprietary connector services.
- Replacing `CoreService`, `TaskStore`, `PolicyService`, or the existing capability adapters.
- Allowing a UI setting to weaken hard containment, destructive confirmation, credential, or provenance rules.
- Silently executing a changed plan under an earlier approval.

## Anti-goals

- A decorative stepper over the existing one-shot Git broker.
- A plan stored only in browser state.
- In-place mutation of an approved plan revision.
- A single broad approval token that can authorize different arguments, paths, or later plan revisions.
- Treating a model response as verification evidence.
- Claiming isolation where only a project boundary is enforced.
- Hiding fallback routing, pending approvals, rejected steps, or failed verification.

## Current-state findings

- The active workspace already collects a project root and outcome, but `execute_project_workspace()` asks one model for one Git action and executes it immediately.
- The Plan, Changes, and Results tabs exist in markup but are hidden.
- `AgentRuntime` already models planning, child tasks, approval-required events, repair limits, verification, and completion, but it is not used by the live workspace route.
- `PlanRevision` and `PlannedStep` contracts exist, but review state, effect metadata, revision editing, and approval digests are not yet modeled.
- `PolicyService` already enforces project-root containment and distinguishes automatic from sensitive operations.
- `ArtifactStore` and task-scoped download APIs exist, but the live workspace returns an empty artifact list.
- `DelegationService`, `ScheduleService`, and `BrowserAdapter` are currently tested scaffolds rather than production workspace services.
- The live MCP stack loads `mcp_servers.json`, launches `stdio` subprocesses, discovers paginated tools, calls allowlisted tools, and integrates them as capability adapters.
- The MCP stack does not yet support Streamable HTTP, OAuth, configuration scopes and project trust, resources, prompts, elicitation, managed organization policy, or a connector-management UI.

## Approaches considered

### 1. Core-first unified workflow — selected

Route the live workspace through the existing durable runtime, extend its plan and approval contracts, then make the UI a projection of task state.

**Benefits:** one source of truth, recoverable task history, exact approvals, honest progress, and a foundation for later capabilities.

**Cost:** touches the API facade, runtime, contracts, policy, persistence, and frontend together; requires migration and compatibility testing.

### 2. UI-first workflow

Add four visible stages around the current endpoint, keeping plans and approvals largely in the browser.

**Rejected because:** it would look complete while execution remained one-shot and non-durable.

### 3. Capability-first expansion

Add documents, spreadsheets, research, schedules, and file organization before unifying orchestration.

**Rejected because:** every new capability would deepen the split between the product route and the existing core runtime.

## Domain model

### Task phase

Every workspace task exposes one of these phases:

- `describe`
- `planning`
- `plan_review`
- `executing`
- `verifying`
- `delivering`
- `completed`
- `blocked`
- `failed`
- `cancelled`

Phase changes are append-only task events. The current phase is derived from events; it is not a second mutable state record.

### Plan revisions

Extend `PlanRevision` so a stored revision contains:

- stable `plan_id` and monotonically increasing `revision`;
- the exact `goal_id` and `goal_revision` it serves;
- an ordered tuple of `PlannedStep` values;
- a summary and expected deliverables;
- revision author (`planner`, `user`, or `system`);
- parent revision and revision reason;
- canonical digest;
- review status: `draft`, `in_review`, `approved`, `rejected`, `superseded`, or `executed`.

Each step adds:

- human title and purpose;
- explicit dependencies;
- capability, operation, target, and bounded arguments;
- effect class;
- expected evidence and output references;
- optional provider-neutral origin references for the skill, Skillset, plugin, command, or agent profile that proposed it;
- review status and canonical digest.

Approved revisions are immutable. Any direct edit or model-assisted revision creates a new revision. The earlier revision remains available in task history and becomes `superseded` when the replacement enters review.

### Revision invalidation

- Editing the plan summary or deliverables creates a new revision and invalidates whole-plan approval.
- Editing, adding, deleting, or reordering a step creates a new revision and invalidates whole-plan approval.
- The changed step and every transitive dependent step return to `pending` review.
- An unchanged independent step may retain an explicit step approval only when its canonical digest and policy snapshot are identical.
- Rejecting a step blocks plan approval until the step is removed or replaced in a newer revision.
- No revision can execute unless all required approvals for that exact revision are satisfied.

### Completed-step carry-forward

When execution returns to planning after one or more steps completed, the new revision carries those steps forward with the same stable step ID, canonical digest, result references, and `completed` disposition. A carried-forward completed step is evidence, not executable work: dependency checks may rely on it, but the runtime never dispatches it again. If the planner truly needs to repeat an effect, it must create a new step ID with a new digest, explain why repetition is required, and obtain whatever approval the current policy requires. This rule prevents revision churn or restart recovery from duplicating effects.

### Review actions

The user can act at plan or step scope:

- **Approve** — approve the exact digest shown.
- **Reject** — record a required reason and block execution.
- **Edit directly** — edit bounded fields in a structured form and create a user-authored revision.
- **Request revision** — submit guidance; the planner proposes a new revision that returns to review.

Whole-plan approval applies to all currently reviewable steps in that exact revision. Step-level approvals support incremental review. If both exist, the most recent exact-digest decision controls; a later rejection blocks execution.

A rejection is final for that exact revision and digest. The approve endpoints reject a later attempt to reverse it. Recovery requires a newer revision that removes or replaces the rejected plan or step, preserving an unambiguous audit history.

One planned step maps to exactly one capability call. A task that needs multiple adapter calls must represent them as separate steps with explicit dependencies. This keeps approval, execution, evidence, retry, and delivery boundaries identical.

### Direct-edit boundaries

At plan scope, users may edit the summary, expected deliverables, step order, and the set of steps. At step scope, users may edit title, purpose, dependencies, select a capability and operation from the currently registered catalog, choose a project-contained target, and edit arguments through the selected adapter's declared input schema.

Users cannot directly edit task/project identity, plan or step IDs, revision numbers, effect class, policy snapshot, digests, review state, execution state, evidence, artifact references, or system provenance. The server recomputes effect class and all digests. Argument payloads retain the existing JSON-size bounds plus adapter-specific schemas; the UI never offers raw contract JSON as the normal editor.

Origin references are provenance only. A skill describes reusable instructions; a Skillset groups routing references; and a future plugin may bundle skills, connector definitions, commands, agent profiles, templates, and assets. None of these origins grants a capability, connector login, credential, command approval, or external-effect permission. Alpha.12 displays the origin and applies the same plan and policy gates as an unbundled request.

### Connector-safe step contract

Alpha.12 does not build the alpha.13 connector platform, but it makes connector work a first-class, safely reviewable plan step. A connector-backed `PlannedStep` stores server identity, tool identity, tool-schema digest, normalized argument digest, declared annotations, requested credential/scopes reference, data-origin summary, effect class, and redacted evidence expectations. Secrets, access tokens, refresh tokens, authorization codes, and resolved credential values are never plan fields, events, digests shown to the user, or project files.

The runtime applies these rules:

- one connector step maps to exactly one `tools/call` operation;
- connector discovery is not authority to execute a tool;
- a changed server identity, tool schema, argument digest, requested scope, effect classification, or policy snapshot invalidates approval;
- `readOnlyHint` and `idempotentHint` are advisory inputs, never sufficient authority by themselves;
- an unknown or missing effect classification defaults to `ask` and cannot be promoted to `allow` by the adapter;
- connector reads remain `network` operations under the alpha.12 policy table, while remote mutations are `external_effect`, credential access is `credential_use`, and destructive remote actions are `destructive`;
- connector results retain server/tool provenance, are bounded by configured result limits, and are redacted before task events or model context when policy marks fields sensitive;
- interrupted external effects are never replayed automatically, including when a tool claims idempotence; a retry creates a separately recorded dispatch decision;
- project containment does not imply remote-data authorization. The connector's authenticated principal and granted scopes remain independent policy inputs.

Alpha.13 may replace the transport and authorization implementations behind this contract, but it must not broaden an already approved alpha.12 step.

## Execution policy

### Presets

Settings exposes three presets and an Advanced section.

#### Balanced — default

- Automatically allow local read, search, context assembly, plan generation, and non-mutating inspection.
- Require approval before file changes, checkpoint restore, commands, network access, installation, Git commit/push, connector calls with external effects, and other mutations.
- Require strong confirmation for destructive operations.
- Allow an approved plan step to serve as the action approval only when the runtime call exactly matches the approved step digest and policy snapshot.

#### Strict

- Require approval before every capability call, including reads and searches.
- Permit harmless UI/session bookkeeping without prompts.
- Retain strong confirmation for destructive operations.

#### Autonomous

- Automatically allow operations the policy marks automatic, including bounded local edits and tests when explicitly enabled by the preset policy table.
- Require one explicit human approval of the generated plan structure before execution begins.
- Continue to require approval for network access, installation, credential use, Git publication, external connector effects, budget overrides, and destructive operations.
- Never bypass hard safety rules.

### Advanced overrides

Advanced Settings lists registered capabilities and their effect classes. Each override is `allow`, `ask`, or `deny` and may be global-default or project-specific.

Precedence, highest first:

1. hard safety denial or strong-confirmation rule;
2. task-specific denial;
3. project-specific capability override;
4. global capability override;
5. selected preset;
6. built-in safe default (`ask`).

At task creation, JSON_CODR stores an immutable policy snapshot with the task. Later Settings changes affect new tasks only unless the user explicitly applies the new policy to a paused task, which invalidates pending approvals.

Settings schema advances from version 2 to version 3. Migration maps existing persistent grants without broadening them and selects Balanced when no execution policy exists.

### Authoritative effect table

Every registered capability declares exactly one effect class. An adapter cannot choose its effect class at runtime.

| Effect class | Examples | Balanced | Strict | Autonomous |
|---|---|---:|---:|---:|
| `observe` | read, search, inspect, context assembly, planning | allow | ask | allow |
| `bounded_edit` | project-contained file create/update with checkpoint | ask | ask | allow |
| `test` | registered non-mutating test adapter | ask | ask | allow |
| `command` | generic terminal or process execution | ask | ask | ask |
| `network` | remote read or request | ask | ask | ask |
| `install` | package, component, provider, or tool installation | ask | ask | ask |
| `git_local` | commit, branch, merge, restore | ask | ask | ask |
| `publish` | push, pull request, release, message, or remote write | ask | ask | ask |
| `external_effect` | connector action that changes another system | ask | ask | ask |
| `credential_use` | accessing or forwarding protected credentials | ask | ask | ask |
| `budget_override` | exceeding configured resource or token budget | ask | ask | ask |
| `destructive` | delete, overwrite without checkpoint, force operation | strong confirm | strong confirm | strong confirm |

`allow` means the policy can dispatch an exact valid step without a new action prompt. `ask` requires exact-digest approval. `strong confirm` requires the existing second confirmation and cannot be overridden. UI/session bookkeeping that has no capability effect remains automatic in all presets.

Under Balanced, approving the whole plan or an individual step supplies the exact-digest approval for its `ask` steps. Under Strict, plan approval accepts the structure only; each capability call still pauses immediately before dispatch. Under Autonomous, the user first approves the exact plan structure; after that approval, `allow` steps require no additional action approval, while every `ask` and `strong confirm` step behaves as shown above.

### Applying changed policy to a paused task

Only tasks in `plan_review`, `blocked`, or `approval_required` may adopt the current Settings policy. `POST /api/tasks/{task_id}/policy/apply` requires the expected task version and intended settings-policy digest. It appends a policy-change event, stores a new immutable snapshot, creates a new plan revision with reason `policy_changed`, preserves completed steps under the carry-forward rule, and invalidates every pending plan/step approval. Running, verifying, delivering, and terminal tasks reject the operation with HTTP 409.

## Approval security

An approval record contains:

- principal;
- project and resolved project root;
- task and optional child task;
- plan ID and revision;
- step ID;
- step digest;
- capability and operation;
- target path and normalized argument digest;
- effect class;
- policy-snapshot digest;
- decision, timestamp, and optional rejection/revision reason.

The runtime recomputes this material immediately before dispatch. Any mismatch pauses the task with a new approval request. Approval cannot authorize a path outside the project root, override a denial, or satisfy destructive strong confirmation.

## Runtime architecture

### Workspace submission

`POST /api/workspace/tasks` remains the frontend entry point but becomes a compatibility facade:

1. validate the session, project root, selected model, and attachments;
2. create a durable `TaskCommand` and accepted goal;
3. snapshot the selected execution policy;
4. start `AgentRuntime` asynchronously;
5. return HTTP 202 with task identity, route disclosure, initial phase, and event URL.

The endpoint must not call `execute_project_workspace()` directly.

### Planning

The planner can call only capabilities allowed during planning by the policy snapshot. Under Balanced this is read/search/inspection. It produces a complete `PlanRevision` before the first effectful call.

The task pauses in `plan_review` whenever required review is incomplete. User edits and requested revisions append plan events and resume planning/review without replacing the task.

Balanced, Strict, and Autonomous all require explicit human acceptance of the exact plan structure before effectful execution. Autonomous differs only after that acceptance: its `allow` steps proceed without an additional action prompt, while `ask` and `strong confirm` steps retain their policy gates.

MCP discovery available during planning may describe configured servers and their approved tool schemas, but it may not perform connector calls. A connector call is always represented as an explicit plan step carrying the connector-safe metadata above. Alpha.12 does not expose resource or prompt discovery because those protocol surfaces belong to alpha.13.

### Execution

Alpha.12 executes ready steps sequentially in dependency order. Each effectful step:

1. checks exact approval and current project fingerprint;
2. creates a checkpoint when the adapter supports restoration;
3. creates a child `TaskCommand` linked to the plan revision and step;
4. streams child events into the parent timeline;
5. records outputs, evidence, artifacts, and changed paths;
6. stops on rejection, permission requirement, stale baseline, failure, or cancellation.

If execution discovers a required action not present in the approved revision, the planner must create a new revision and return to `plan_review`.

### Project fingerprint and baseline refresh

The authoritative fingerprint is `ProjectAdapter.snapshot()`: a canonical SHA-256 over the normalized relative path and bytes of every file returned by `ProjectReader`, using its existing exclusions for repository metadata, JSON_CODR state, ignored content, and unsafe entries. Git adapters may retain a Git-specific dirty fingerprint as additional evidence, but it does not replace the project fingerprint.

An explicit baseline refresh is available only while paused. It snapshots the current project, appends a baseline-refresh event, creates a new plan revision with reason `baseline_changed`, carries forward completed steps only when their stored post-step fingerprint is an ancestor of the refreshed state, and invalidates pending approvals. If ancestry cannot be proved, the task blocks for re-planning instead of guessing.

### Verification and delivery

Verification evaluates the goal criteria against fresh evidence and the current project fingerprint. It cannot use the planner's assertion as evidence.

Delivery contains:

- outcome summary;
- final task and verification status;
- requested and effective model/engine;
- executed plan revision;
- changed-path summary and checkpoint/undo availability;
- child-step results and failures;
- artifact manifest with authorized download links;
- warnings, unresolved criteria, and next actions.

`WorkspaceTaskResponse.artifact_references` is populated from `ArtifactStore`. Artifact downloads remain task-scoped and path-independent.

## API surface

Keep existing task read, event, steer, cancel, retry, restore, capability, and artifact endpoints. Add plan-specific endpoints under the task:

- `GET /api/tasks/{task_id}/plans`
- `GET /api/tasks/{task_id}/plans/{revision}`
- `POST /api/tasks/{task_id}/plans/{revision}/approve`
- `POST /api/tasks/{task_id}/plans/{revision}/reject`
- `POST /api/tasks/{task_id}/plans/{revision}/revise`
- `POST /api/tasks/{task_id}/plans/{revision}/edit`
- `POST /api/tasks/{task_id}/plans/{revision}/steps/{step_id}/approve`
- `POST /api/tasks/{task_id}/plans/{revision}/steps/{step_id}/reject`
- `POST /api/tasks/{task_id}/plans/{revision}/steps/{step_id}/revise`
- `POST /api/tasks/{task_id}/plans/{revision}/steps/{step_id}/edit`
- `POST /api/tasks/{task_id}/policy/apply`
- `POST /api/tasks/{task_id}/baseline/refresh`

Every mutating request carries `expected_plan_digest`. Stale requests return HTTP 409 with the current revision. Validation errors return RFC 9457-compatible problem details without exposing secrets or unapproved arguments.

## User interface

### Phase navigation

Add a compact four-phase stepper above the task canvas. It shows current, completed, blocked, and available phases without pretending future phases are complete. On narrow screens it becomes a horizontally scrollable tab list with visible labels.

### Describe

Reuse the current project root, prompt/outcome, attachments, model, and agent controls. Add the policy preset selector with a link to Advanced Settings. Submission announces that read-only planning has started.

### Plan

Activate the Plan tab. It contains:

- plan revision, author, reason, digest-shortcode, and policy preset;
- plan summary and expected deliverables;
- ordered step cards with dependencies, effect badge, target summary, evidence expectation, and review state;
- plan controls: Approve, Reject, Edit plan, Revise plan;
- step controls: Approve, Reject, Edit step, Revise step;
- revision history and a diff between the current and immediately previous revision.

Direct editing uses structured fields, never raw contract JSON. Model-assisted revision opens an instruction box and previews the proposed revision before replacing the review candidate. Rejection and revision requests require a reason. Focus returns to the changed plan or step after re-render.

### Execute and Changes

Activate Changes while execution is running. Show the active step, queued steps, approvals, commands or capability summaries, changed paths, checkpoints, verification evidence, and child-task events. Raw sensitive arguments remain redacted.

### Deliver and Results

Activate Results when verification begins and keep it available after completion. Render the delivery contract as readable sections and download cards rather than raw JSON. Stop, Retry, Steer, and Undo continue to work from the shared task status bar.

## Persistence and recovery

- Plans, revisions, review decisions, policy snapshots, and phase transitions are append-only task events or normalized records keyed to task IDs.
- Refreshing or reopening a task reconstructs the exact phase and review state from durable storage.
- Restart recovery never auto-resumes an effectful step whose completion is unknown; it marks the step interrupted and asks the user to retry or revise.
- Duplicate approval submissions are idempotent for the same digest.
- A task cannot use approval records from another task, project, policy snapshot, revision, or principal.

## Accessibility and responsive behavior

- All phase controls and plan actions are keyboard reachable with visible focus.
- Plan and step statuses use text plus icons, not color alone.
- Revision dialogs have programmatic names, descriptions, validation messages, and deterministic focus restoration.
- Live phase and approval changes use bounded `aria-live` announcements.
- Reduced-motion preferences disable animated phase transitions.
- Strict-mode read approvals can be handled without losing the user's position in the plan.

## Failure behavior

- Stale project fingerprint: pause and require re-plan or explicit baseline refresh.
- Stale plan digest: reject the request with current revision metadata.
- Planner produces an unsupported capability: keep the plan in review and mark the step invalid.
- Adapter becomes unavailable: block that step without discarding prior results.
- Approval denied: block the plan until a new revision removes or replaces the step.
- Artifact write fails: verification may complete, but delivery reports the missing artifact and cannot claim it was delivered.
- Browser disconnect: execution continues only according to the stored policy snapshot; pending approvals remain paused.
- Server restart during an effect: mark interrupted and do not replay automatically.

## Testing strategy

### Contracts and persistence

- Plan revision round trips, digest stability, immutable approved revisions, dependency validation, and migration from settings schema 2 to 3.
- Direct plan/step edit and model-assisted revision create new revisions and invalidate the correct approvals.
- Stale-digest and cross-task approval replay are rejected.

### Policy

- Balanced, Strict, and Autonomous decision tables for every registered effect class.
- Advanced override precedence and hard-rule non-bypass.
- Task policy snapshots remain stable when Settings changes.
- Destructive operations always retain strong confirmation.

### Runtime

- Workspace submission returns a durable task and never invokes the legacy one-shot path.
- Balanced planning can read/search but pauses before its first effect.
- Exact approved steps execute; altered arguments return to review.
- Checkpoint, child task, cancellation, retry, repair limit, verification, and delivery events remain linked to one task.
- Restart and stale-baseline recovery do not duplicate effects.

### API and UI

- Whole-plan and per-step approve/reject/edit/revise flows, including HTTP 409 on stale edits.
- Phase stepper, Plan/Changes/Results tabs, focus restoration, announcements, narrow viewport, reduced motion, and keyboard-only use.
- Refresh reconstructs an in-review or partially executed task.
- Artifact references render authorized downloads and never expose filesystem paths.

### Compatibility

- Existing single-model, automatic-model, and multi-model selections retain truthful route disclosure.
- Existing terminal approvals, destructive confirmation, attachments, skills, MCP adapters, undo, and conversation exports remain functional.
- The legacy workspace response shape remains parseable while the frontend moves to task events.

### Connector safety

- Existing approved `stdio` MCP servers still discover and call allowlisted tools.
- Every connector call is represented by one exact plan step and uses its server, tool-schema, arguments, effect, and policy digests.
- A changed tool schema, effect annotation, requested scope, or server identity invalidates approval.
- Unknown connector effects default to `ask`; remote writes and destructive actions cannot inherit read-only approval.
- Secrets and tokens never enter plan records, task events, downloadable artifacts, logs, or frontend state.
- Interrupted connector effects do not replay automatically, and retries remain separately auditable.

## Rollout

1. Add contracts, persistence, and settings migration behind `guided_task_flow` disabled by default.
2. Add plan APIs and runtime integration with contract/integration tests.
3. Add the four-phase UI and browser tests.
4. Enable the flag in development and run legacy/new route parity tests.
5. Make the guided flow default for alpha.12 while retaining a temporary diagnostic fallback to the legacy route.
6. Remove the fallback only after end-to-end verification on Windows with the supported Python runtime split documented.

## Deferred revisions

- **alpha.13 — MCP, connectors, skills, and plugins:** Streamable HTTP with compatible transport negotiation, OAuth authorization and secure credential storage, local/project/user scopes, project trust, tools/resources/prompts/elicitation, connection status and recovery, connector settings UI, schema/result validation, per-tool policy controls, and provider-neutral plugin bundles containing skills, connector definitions, slash commands, agent profiles, templates, and assets. Functional parity targets open capabilities; it does not copy third-party branding or depend on proprietary hosted connectors.
- **alpha.14 — managed connectors and orchestration:** organization identity and administration, managed connector definitions, server/tool allow-ask-block enforcement, connector audit UI, long-running MCP tasks and event channels, deferred tool discovery, production parallel delegation, isolated child worktrees, merge review, and durable schedules.
- **alpha.15 — typed work products:** document, spreadsheet, presentation, PDF, research, and file-organization capabilities with task-owned artifacts.

## Builder discretion

- Exact internal class/module split where existing files would become unwieldy.
- Visual iconography and microcopy consistent with NOC Light and the other appearance presets.
- Database normalization details, provided task reconstruction remains deterministic and migrations remain reversible.
- Whether plan revision diffs are computed server-side or in the client, provided the API exposes enough immutable revision data to verify them.
