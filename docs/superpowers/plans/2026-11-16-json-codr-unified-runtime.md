# JSON_CODR Unified Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON_CODR's tool-specific beta paths with one durable local agent runtime that can inspect, edit, execute, verify, recover, and report through the same project/thread/task model.

**Architecture:** `CoreService` owns task submission and delegates one observable loop to `AgentRuntime`; `TaskStore` is the sole durable task authority, `PolicyService` authorizes concrete capabilities, and `CapabilityRegistry` resolves replaceable adapters. Existing beta services are wrapped, parity-tested, and then made unreachable from UI and transport handlers; optional libraries and incompatible Python packages run behind versioned provider processes.

**Tech Stack:** Python 3.15 core, FastAPI, Pydantic, asyncio, SQLite, WebSockets, Ollama, vanilla JavaScript, xterm.js, unittest; isolated Python 3.12/3.14 providers for incompatible optional modules.

**Spec:** `docs/superpowers/specs/2026-11-16-borg-unified-system-design.md`

## Global Constraints

- Product, API, schema, persistence, UI, and log names use JSON_CODR-neutral terminology; BORG remains only a historical alpha codename.
- `CoreService` is the only task-producing boundary and `TaskStore` is the only durable task-state authority.
- No UI handler, HTTP/WebSocket route, schedule, or model action directly mutates files, launches subprocesses, executes Git, installs dependencies, invokes inference, or calls REA/Ghidra.
- Preserve useful beta data and last-known-good direct Ollama behavior until its permanent replacement passes parity tests.
- Report requested model, effective model, native/brokered status, adapter, runtime, fallback reason, and verification evidence separately.
- CPU remains the compatibility fallback; optimized hardware is selected only from model-specific verified evidence.
- Foreground work edits the active project behind a checkpoint; background and concurrent editing uses isolated Git worktrees.
- Unsupported optional packages run in locked provider environments and never alter the Python 3.15 core environment.
- Imported code remains quarantined until provenance, policy, environment, and functional probes pass.
- Local edits apply immediately behind a checkpoint; commits, pushes, publishing, and destructive actions remain separately authorized.

## Review Focus

- A restart during execution preserves events and marks unresolved work interrupted rather than complete; Task 2 tests this.
- Concurrent clients and child agents cannot execute one command twice or edit one worktree concurrently; Tasks 3 and 7 test this.
- An external editor or Git process changing the project pauses conflicting work instead of being overwritten; Task 4 tests this.
- Failure of an optional provider or accelerator leaves the core project and last-known-good Ollama route usable; Tasks 5 and 6 test this.
- Authorization granted to one project, schedule, or capability cannot escape its approved roots or credential scope; Tasks 3 and 8 test this.

---

### Task 1: Permanent contracts and capability registry

**Files:**
- Create: `web_app/core/__init__.py`
- Create: `web_app/core/contracts.py`
- Create: `web_app/core/capabilities.py`
- Test: `test_core_capabilities.py`

**Interfaces:**
- Produces: schema-versioned validated task/thread/project/command identifiers, `TaskStatus`, `ExecutionMode`, `ModelScope`, `ManifestAuthority`, `RuntimeIdentity`, `CapabilityManifest`, `ProbeObservation`, `CapabilityResult`, `TaskCommand`, `TaskEvent`, and `TaskRecord`.
- Produces: `CapabilityRegistry.register(manifest, adapter_factory, probe_verifier)`, `resolve(request, context)`, `probe(request, context)`, and `describe()`.

- [x] **Step 1: Write failing registry contract tests**

Test deterministic registration, duplicate rejection, explicit model applicability, deep command immutability, strict contract fields and identifiers, technical probes independent from authorization, model/mode-specific readiness, structured probe evidence, package presence not implying readiness, and native/brokered separation.

- [x] **Step 2: Run the focused test and verify failure**

Run: `C:\Python315\python.exe -m unittest test_core_capabilities -v`

Expected: FAIL because `web_app.core` does not exist.

- [x] **Step 3: Implement immutable Pydantic contracts and the in-memory registry**

Keep registry resolution free of execution and persistence. Define stable validated identifiers, canonical bounded JSON payloads, explicit model applicability, manifest authority, host-owned probe verification, and distinct technical-readiness and authorization checks.

- [x] **Step 4: Run focused tests**

Run: `C:\Python315\python.exe -m unittest test_core_capabilities -v`

Expected: PASS.

- [x] **Step 5: Commit**

```powershell
git add web_app/core test_core_capabilities.py
git commit -m "feat(core): add unified capability contracts"
```

### Task 2: Durable task, event, artifact, and checkpoint state

**Files:**
- Create: `web_app/core/store.py`
- Create: `web_app/core/artifact_store.py`
- Test: `test_core_store.py`

**Interfaces:**
- Consumes: Task and event contracts from Task 1.
- Produces: `TaskStore.create(command)`, `append(task_id, event)`, `get(task_id)`, `events(task_id, after_sequence)`, `children(task_id)`, `request_cancel(task_id)`, and `recover_interrupted()`.
- Produces: `ArtifactStore.put(stream, metadata)`, `open(artifact_id)`, `prune(policy)`, and `export_manifest(task_id)`.

New IDs use UUIDv7. Event envelopes retain task sequence and causation while carrying CloudEvents-compatible identity metadata. Draft events and durable events are separate sibling contracts; only `TaskStore` assigns durable identity and sequence. Persisted hashes use RFC 8785 canonical JSON, and event digests form a verified per-task hash chain. Mutation records carry expected-version or expected-digest preconditions; HTTP mappings use strong `If-Match` semantics and RFC 9457 problem details.

- [x] **Step 1: Write failing persistence tests**

Cover atomic task creation, monotonic per-task sequences, concurrent append serialization, idempotency keys, parent-child links, artifact hashes, redacted metadata, retention without broken references, restart recovery, and unresolved running tasks becoming `interrupted` rather than `completed`.

- [x] **Step 2: Run the focused test and verify failure**

Run: `C:\Python315\python.exe -m unittest test_core_store -v`

Expected: FAIL because the store modules do not exist.

- [x] **Step 3: Implement a SQLite TaskStore and content-addressed ArtifactStore**

Use one SQLite transaction for each state transition and event append. Store large payloads by artifact reference; never persist raw credentials.

- [x] **Step 4: Run focused tests**

Run: `C:\Python315\python.exe -m unittest test_core_store -v`

Expected: PASS.

- [x] **Step 5: Commit**

```powershell
git add web_app/core test_core_store.py
git commit -m "feat(core): persist tasks events and artifacts"
```

### Task 3: Policy service and sole execution boundary

**Files:**
- Create: `web_app/core/policy.py`
- Create: `web_app/core/service.py`
- Create: `web_app/core/adapters.py`
- Test: `test_core_service.py`

**Interfaces:**
- Consumes: `CapabilityRegistry`, `TaskStore`, and `ArtifactStore`.
- Produces: `CapabilityAdapter.execute(call, context) -> AsyncIterator[AdapterEvent]`.
- Produces: `PolicyService.evaluate(principal, project, capability_call) -> PolicyDecision` and persistent grant/revoke methods.
- Produces: `CoreService.submit(command)`, `steer(task_id, input)`, `cancel(task_id)`, `retry(task_id)`, `restore(checkpoint_id)`, and `subscribe(task_id, after_sequence)`.

- [x] **Step 1: Write failing service and policy tests**

Test one execution per idempotency key, project-root escape rejection, automatic reads/search/tests/bounded edits, separate approval for network/install/commit/push/destructive operations, schedule-scoped grants, credential references never entering events, brokered fallback allowed only inside the same local privacy/cost boundary, cancellation, and adapter failure producing a truthful failed attempt.

- [x] **Step 2: Run the focused test and verify failure**

Run: `C:\Python315\python.exe -m unittest test_core_service -v`

Expected: FAIL because service and policy modules do not exist.

- [x] **Step 3: Implement the dispatcher, adapter protocol, and persistent policy**

Commit task intent before dispatch; append adapter events through `TaskStore`; require a concrete `PolicyDecision` before every capability call.

- [x] **Step 4: Run focused tests**

Run: `C:\Python315\python.exe -m unittest test_core_service -v`

Expected: PASS.

- [x] **Step 5: Commit**

```powershell
git add web_app/core test_core_service.py
git commit -m "feat(core): add policy-controlled execution boundary"
```

### Task 4: Project, checkpoint, worktree, Git, and terminal capabilities

**Files:**
- Create: `web_app/core/project_adapter.py`
- Create: `web_app/core/git_adapter.py`
- Create: `web_app/core/terminal_adapter.py`
- Create: `web_app/core/project_watch.py`
- Modify: `web_app/workspace.py`
- Modify: `web_app/git_broker.py`
- Modify: `web_app/terminal.py`
- Test: `test_core_project_runtime.py`

**Interfaces:**
- Produces capabilities `project.read`, `project.search`, `project.patch`, `project.watch`, `checkpoint.create`, `checkpoint.restore`, `worktree.create`, `worktree.merge`, `terminal.session`, `terminal.execute`, `git.inspect`, `git.commit`, `git.sync`, and `git.push`.
- Produces `ProjectSnapshot`, `CheckpointRecord`, `ExternalChangeEvent`, and `TerminalSessionRecord`.

- [x] **Step 1: Write failing parity and conflict tests**

Extend existing workspace, Git, and terminal cases with pre-edit checkpoints, immediate foreground edits, background worktree isolation, merge evidence, external file/Git changes pausing a conflicting task, interactive terminal input/output attached to one task, command history, cancellation, path escape rejection, and exact rollback.

- [x] **Step 2: Run focused old and new tests and verify the new cases fail**

Run: `C:\Python315\python.exe -m unittest test_workspace test_git_broker test_terminal test_core_project_runtime -v`

Expected: existing tests pass and new unified-runtime cases fail.

- [x] **Step 3: Wrap existing implementations behind capability adapters**

Keep subprocess and Git mechanics in their owning services, but expose mutation only through registered adapters. Use native Git worktrees and captured process identities.

- [x] **Step 4: Migrate project, Git, and terminal transport handlers to `CoreService`**

Remove direct mutation calls from migrated handlers after parity passes; an external shell remains explicitly outside tracking guarantees.

- [x] **Step 5: Run focused tests**

Run: `C:\Python315\python.exe -m unittest test_workspace test_git_adapter test_git_broker test_terminal test_core_project_runtime -v`

Expected: PASS.

- [x] **Step 6: Commit**

```powershell
git add web_app test_workspace.py test_git_adapter.py test_git_broker.py test_terminal.py test_core_project_runtime.py
git commit -m "refactor(core): unify project git and terminal execution"
```

### Task 5: Model routing, context, memory, and the agent loop

**Files:**
- Create: `web_app/core/context_service.py`
- Create: `web_app/core/memory.py`
- Create: `web_app/core/router.py`
- Create: `web_app/core/agent_runtime.py`
- Create: `web_app/core/inference_adapter.py`
- Modify: `web_app/context.py`
- Modify: `web_app/ollama_service.py`
- Modify: `web_app/inference/router.py`
- Test: `test_agent_runtime.py`

**Interfaces:**
- Produces: `ContextService.assemble(thread_id, task_id, budget) -> ContextBundle` and `compact(thread_id) -> CompactionRecord`.
- Produces: `ExecutionRouter.resolve(requirements, preferences) -> ExecutionRoute`.
- Produces: `AgentRuntime.run(task_id)`, `steer(task_id, input)`, and `resume(task_id)`.
- Produces capabilities `inference.generate`, `agent.plan`, `agent.invoke_capability`, and `agent.verify`.

- [x] **Step 1: Write failing agent-loop tests**

Use deterministic fake models and adapters to test read-edit-test-correct-verify completion, steering during a task, native tool calls, brokered calls without false native claims, automatic local fallback, consent for cloud/cost/privacy changes, context-source provenance, compaction retaining links to original events, requested/effective model reporting, and last-known-good CPU/Ollama recovery after provider failure.

- [x] **Step 2: Run focused tests and verify failure**

Run: `C:\Python315\python.exe -m unittest test_agent_runtime test_context test_inference_router -v`

Expected: new agent-runtime cases fail.

- [x] **Step 3: Implement layered context and disposable search indexes**

Keep source records authoritative; use SQLite FTS5 initially and make any vector index rebuildable.

- [x] **Step 4: Implement compatibility-first routing and the observable loop**

Every planned action becomes a concrete capability call authorized by Task 3 and recorded by Task 2. Do not embed filesystem, Git, terminal, or installer behavior in the runtime.

- [x] **Step 5: Migrate ordinary chat generation through `CoreService`**

Preserve the direct Ollama path as a registered last-known-good adapter, not a handler shortcut.

- [x] **Step 6: Run focused inference, context, chat, and runtime tests**

Run: `C:\Python315\python.exe -m unittest test_agent_runtime test_context test_inference_contracts test_inference_compatibility test_inference_router test_web_api -v`

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add web_app test_agent_runtime.py test_context.py test_inference_*.py test_web_api.py
git commit -m "feat(core): add unified local agent runtime"
```

### Task 6: Isolated providers and verified optional capabilities

**Files:**
- Create: `web_app/core/provider_manager.py`
- Create: `web_app/core/provider_protocol.py`
- Create: `web_app/core/credentials.py`
- Modify: `web_app/inference/environments.py`
- Modify: `web_app/inference/sidecar.py`
- Test: `test_provider_manager.py`

**Interfaces:**
- Produces: `ProviderManifest`, `ProviderLock`, `ProviderProcess`, and JSON-lines request/event protocol.
- Produces: `ProviderManager.ensure(manifest)`, `start(provider_id)`, `probe(provider_id)`, `execute(provider_id, call)`, `cancel(call_id)`, and `remove(provider_id)`.
- Produces: `CredentialBroker.put()`, `reference()`, `resolve_for_adapter()`, and `revoke()`.

- [x] **Step 1: Write failing isolation tests**

Test Python-version selection, lock/hash validation, no writes to the core environment, functional probe required after installation, process crash cleanup, cancellation, credential redaction, provider upgrade rollback, optional provider failure leaving direct Ollama functional, and unsupported Python 3.15 packages selecting a 3.12/3.14 provider.

- [x] **Step 2: Run focused tests and verify failure**

Run: `C:\Python315\python.exe -m unittest test_provider_manager test_inference_sidecar -v`

Expected: new provider-manager cases fail.

- [x] **Step 3: Implement locked provider lifecycle and IPC**

Reuse existing inference sidecar patterns where compatible. Record interpreter identity, dependency lock, mounts, network policy, credential scope, and cleanup evidence.

- [x] **Step 4: Run focused tests**

Run: `C:\Python315\python.exe -m unittest test_provider_manager test_inference_sidecar -v`

Expected: PASS.

- [x] **Step 5: Commit**

```powershell
git add web_app/core web_app/inference test_provider_manager.py test_inference_*.py
git commit -m "feat(core): isolate optional capability providers"
```

### Task 7: Language, browser, MCP, REA, Ghidra, and assimilation adapters

**Files:**
- Create: `web_app/core/language_adapter.py`
- Create: `web_app/core/browser_adapter.py`
- Create: `web_app/core/mcp_adapter.py`
- Create: `web_app/core/analysis_adapter.py`
- Create: `web_app/core/assimilation.py`
- Modify: `web_app/skills.py`
- Modify: `web_app/extraction.py`
- Test: `test_core_extended_capabilities.py`

**Interfaces:**
- Produces capabilities `code.parse`, `code.symbols`, `code.diagnostics`, `browser.inspect`, `browser.interact`, `browser.capture`, `mcp.discover`, `mcp.invoke`, `rea.inspect`, `ghidra.analyze`, `component.identify`, `component.install`, `component.enable`, and `component.remove`.
- Produces: `ComponentManifest`, `ProvenanceRecord`, `QuarantineRecord`, and `FunctionalProbeResult`.

- [x] **Step 1: Write failing capability and assimilation tests**

Test Tree-sitter/LSP fallback, browser screenshot and DOM evidence, MCP schemas and permission mediation, REA/Ghidra applicable versus unavailable results, GitHub/local/archive/skill/MCP identification, duplicate content hashes, quarantine, signature/provenance recording, project-only initial enablement, promotion, removal, rollback, and no execution before the functional probe passes.

- [x] **Step 2: Run focused old and new tests and verify new cases fail**

Run: `C:\Python315\python.exe -m unittest test_core_extended_capabilities test_skills test_skills_import test_extraction -v`

Expected: new unified capability cases fail.

- [x] **Step 3: Implement adapters through `ProviderManager` where isolation is required**

Dependencies are pinned only after isolated installation and probe tests pass. Adapter absence must degrade to a clear unavailable result, not break core startup.

- [x] **Step 4: Move skill and component imports behind assimilation**

Preserve installed JSON_CODR skills and envelope formats; eliminate direct installation from HTTP handlers.

- [x] **Step 5: Run focused tests**

Run: `C:\Python315\python.exe -m unittest test_core_extended_capabilities test_skills test_skills_import test_extraction test_dependencies -v`

Expected: PASS.

- [x] **Step 6: Commit**

```powershell
git add web_app test_core_extended_capabilities.py test_skills*.py test_extraction.py test_dependencies.py
git commit -m "feat(core): add verified extended capabilities"
```

### Task 8: Child agents, schedules, hooks, and resource budgets

**Files:**
- Create: `web_app/core/delegation.py`
- Create: `web_app/core/scheduler.py`
- Create: `web_app/core/hooks.py`
- Create: `web_app/core/resources.py`
- Test: `test_core_automation.py`

**Interfaces:**
- Produces: `DelegationService.create_child()`, `send_input()`, `interrupt()`, `wait()`, and `merge_result()`.
- Produces: `ScheduleService.create()`, `enable()`, `disable()`, `trigger()`, and `history()`.
- Produces: `HookRegistry.subscribe(event_type, capability_call)` and `ResourceBudget.evaluate(sample)`.

- [x] **Step 1: Write failing automation tests**

Test autonomous delegation within configured local concurrency/VRAM limits, child context/tool scoping, editing children receiving separate worktrees, deterministic result attribution, no double execution, resource-limit permission requests, inspection-only schedules under default policy, explicit grants for scheduled writes/commits/pushes, missed-run recovery, hook recursion prevention, and all automation submitting through `CoreService`.

- [x] **Step 2: Run focused tests and verify failure**

Run: `C:\Python315\python.exe -m unittest test_core_automation -v`

Expected: FAIL because automation modules do not exist.

- [x] **Step 3: Implement bounded delegation, APScheduler-backed triggers, hooks, and local resource accounting**

Schedulers and hooks submit commands; they never execute capabilities themselves. External agent frameworks remain optional provider implementations.

- [x] **Step 4: Run focused tests**

Run: `C:\Python315\python.exe -m unittest test_core_automation test_core_service test_core_project_runtime -v`

Expected: PASS.

- [x] **Step 5: Commit**

```powershell
git add web_app/core test_core_automation.py
git commit -m "feat(core): add bounded automation and delegation"
```

### Task 9: Unified HTTP API, WebSocket stream, and headless CLI

**Files:**
- Create: `web_app/core/api.py`
- Create: `web_app/core/cli.py`
- Modify: `web_app/app.py`
- Test: `test_core_api.py`
- Test: `test_core_cli.py`

**Interfaces:**
- Produces neutral `/api/tasks`, `/api/projects/{project_id}/threads`, `/api/capabilities`, task steering/cancel/retry/restore endpoints, and `/ws/tasks`.
- Produces `python -m web_app.core.cli run --project ... --output text|json|stream-json` with deterministic exit codes.

- [x] **Step 1: Write failing transport tests**

Test command submission, invalid contracts, permission-required responses, event replay from a cursor, multiple observers, one command execution across reconnect, steering, cancellation, artifact download authorization, structured headless output, exit codes, and redaction.

- [x] **Step 2: Run focused tests and verify failure**

Run: `C:\Python315\python.exe -m unittest test_core_api test_core_cli -v`

Expected: FAIL because the transports do not exist.

- [x] **Step 3: Implement thin transports over `CoreService`**

Routes decode, call one service method, and encode. They contain no product execution logic.

- [x] **Step 4: Run focused transport tests**

Run: `C:\Python315\python.exe -m unittest test_core_api test_core_cli test_web_api -v`

Expected: PASS.

- [x] **Step 5: Commit**

```powershell
git add web_app/core web_app/app.py test_core_api.py test_core_cli.py test_web_api.py
git commit -m "feat(api): expose unified task runtime"
```

### Task 10: One project/thread/task web experience

**Files:**
- Create: `web/core_client.js`
- Create: `web/task_view.js`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/app.css`
- Modify: `web/terminal_keyboard.js`
- Test: `test_core_web.py`
- Test: `test_web_static.py`

**Interfaces:**
- Consumes: Task 9 API and event stream.
- Produces: one client connection and store shared by conversation, resources, terminal, activity, results, diffs, artifacts, permissions, and execution details.

- [x] **Step 1: Write failing static and browser-contract tests**

Test one visible conversation flow, attachment/drop submission, shared task IDs, live event replay, steering, stop/retry/undo, immediate edits without an Apply button, progressive execution details, requested/effective model disclosure, responsive layout, keyboard copy/paste and quit sequence, and absence of Continue/Aider/BORG product controls or API paths.

- [x] **Step 2: Run focused tests and verify failure**

Run: `C:\Python315\python.exe -m unittest test_core_web test_web_static test_terminal_keyboard -v`

Expected: new unified-UI cases fail.

- [x] **Step 3: Implement the shared client store and task view**

Use meaningful state changes rather than continuous repainting. Advanced implementation detail remains collapsed unless needed.

- [x] **Step 4: Replace migrated direct fetches and tool-specific launch controls**

The terminal remains a view of the same runtime; skills, MCP, hardware, and capability management remain settings for that runtime.

- [x] **Step 5: Run static and JavaScript syntax verification**

Run: `C:\Python315\python.exe -m unittest test_core_web test_web_static test_terminal_keyboard -v`

Run: `node --check web/core_client.js; node --check web/task_view.js; node --check web/app.js; node --check web/terminal_keyboard.js`

Expected: all PASS with no syntax output.

- [x] **Step 6: Run the live Playwright acceptance flow**

Verify open project → request inspect/edit/test → observe live activity → steer → review diff/evidence → undo. Verify an optional-adapter failure falls back without losing the task and that no internal executor selection is required.

- [x] **Step 7: Commit**

```powershell
git add web test_core_web.py test_web_static.py test_terminal_keyboard.py
git commit -m "refactor(web): present one JSON_CODR agent workflow"
```

### Task 11: Beta data migration and direct-path architecture gate

**Files:**
- Create: `web_app/core/migration.py`
- Create: `test_core_migration.py`
- Create: `test_core_architecture.py`
- Modify: transport and handler files reported by the architecture test.

**Interfaces:**
- Produces: `MigrationService.inspect(source)`, `migrate(source, destination)`, `verify(report)`, and `rollback(report)`.
- Produces an architecture test that rejects direct mutation and execution outside registered adapters.

- [x] **Step 1: Write failing copy-on-write migration tests**

Test preservation of projects, JSON_CODR skills, general settings, compatible permissions, benchmarks, imported resources, and useful conversations; secrets are excluded, Continue/Aider runtime configuration is archived but not activated, malformed records are reported, the beta source remains byte-for-byte unchanged, and migration can be rolled back.

- [x] **Step 2: Write the failing architecture boundary test**

Reject direct subprocess, filesystem mutation, Git mutation, installer, inference, REA, and Ghidra calls from UI, transport, scheduler, hook, and agent modules. Permit them only in registered adapters and provider-process entry points.

- [x] **Step 3: Run focused tests and record failures**

Run: `C:\Python315\python.exe -m unittest test_core_migration test_core_architecture -v`

Expected: FAIL with missing migration and remaining beta direct paths.

- [x] **Step 4: Implement copy-on-write migration and remove every reported direct path**

Do not add architecture-test exemptions for product behavior. Move behavior behind a capability or remove obsolete beta code.

- [x] **Step 5: Run migration, architecture, and affected beta parity tests**

Run: `C:\Python315\python.exe -m unittest test_core_migration test_core_architecture test_settings test_skills test_localperf test_coding_agents -v`

Expected: PASS; coding-agent compatibility data may migrate, but no Continue/Aider runtime dependency remains.

- [x] **Step 6: Commit**

```powershell
git add web_app test_core_migration.py test_core_architecture.py
git commit -m "refactor(core): complete unified runtime migration"
```

### Task 12: Integrated verification and alpha release

**Files:**
- Modify: `README.md`
- Modify: `web_app/version.py`
- Modify: dependency and launcher files identified during implementation.
- Test: existing tracked test suite.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented JSON_CODR unified workflow and `V1.0.18-alpha.1` release metadata.

- [ ] **Step 1: Run all tracked Python tests**

Run: `C:\Python315\python.exe -m unittest discover -v`

Expected: PASS with no skipped unified-runtime acceptance tests.

- [ ] **Step 2: Run JavaScript and patch validation**

Run syntax checks for every tracked `.js` file changed by the branch and `git diff --check`.

Expected: no output indicating errors.

- [ ] **Step 3: Run the complete local acceptance matrix**

Verify direct chat, terminal-backed work, brokered non-tool model work, native-tool model work, child-agent isolation, browser verification, MCP, skill assimilation, REA/Ghidra applicability, CPU fallback, one available accelerator, restart/reconnect, cancellation, rollback, schedule permissions, migration, export, and removal. Record only real evidence returned by adapters.

- [ ] **Step 4: Update user documentation and version**

Describe the project/thread/task workflow, ordinary controls, permissions, undo, execution details, assimilation, schedules, and migration without narrating internal modules. Set version to `V1.0.18-alpha.1` consistently.

- [ ] **Step 5: Restart the local alpha system and rerun the primary Playwright workflow**

Expected: the URL reports `V1.0.18-alpha.1`; a user completes a coding task without selecting an internal executor; live events, diff, verification, checkpoint, and undo all work.

- [ ] **Step 6: Commit the release checkpoint**

```powershell
git add README.md web_app/version.py
git commit -m "release: publish V1.0.18-alpha.1"
```
