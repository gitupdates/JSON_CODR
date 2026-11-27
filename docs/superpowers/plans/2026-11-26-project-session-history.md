# Project Session History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Workspace a clean per-page live session and owner/project-scoped, keyword-searchable saved history that is automatically retrieved for relevant future prompts.

**Architecture:** A focused `ProjectSessionService` stores immutable project snapshots, deterministic summaries, and structural change identifiers, then restores snapshots into newly allocated live sessions. Authenticated project routes enforce owner/project scope; `MemoryStore` provides the FTS5 projection, and `ContextAssembler` retrieves bounded relevant Previous Session History with source refs before inference. The browser owns only the current page session and renders saved history separately in Context & Files.

**Tech Stack:** Python 3.11+; FastAPI; Pydantic v2; SQLite FTS5; vanilla JavaScript; Node-based view tests; `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-26-project-session-history-design.md`

## Global Constraints

- Saved snapshots are immutable after atomic promotion and are scoped to both authenticated owner and server-resolved registered project identity.
- Saving keeps the live session active; restoring creates a different live session ID; New Session is the explicit clean-slate action during a loaded page.
- Fresh page load never reopens a browser-stored session and never renders earlier unsaved messages.
- Scoped SQLite/FTS5 is a rebuildable search projection; snapshot files remain authoritative when memory is disabled or indexing is rejected.
- FTS history contains compact summaries only, with `retain_details=false`, nonempty source refs, deterministic idempotency, and at most 65,536 characters.
- Private reasoning, binary data, terminal processes, pending approvals, and in-flight tasks are excluded from compaction/restore state.
- Existing legacy sessions and exports remain readable and are not automatically promoted or deleted.
- Ollama bare 64-hex and `sha256:`-prefixed digests canonicalize to one identity; explicit quarantine remains blocking while untested installed artifacts remain manually probeable.
- Ask All Available Models uses the page-scoped live session and identity mutation headers for every POST.
- All mutating routes use existing browser identity/CSRF enforcement and mutation inventory.
- Existing modified RED-test files and the untracked `.tmp` directory remain intact.

## Review Focus

- Bare-digest state migration must not revive a digest-mismatched or explicitly quarantined artifact; pin in Task 1.
- All-model 401/403 start/cancel responses must restore usable controls and report server detail; pin in Task 1.
- Concurrent message/attachment mutation during save must yield a consistent snapshot or fail without promotion; pin in Task 2.
- Symlinks/reparse points, partial attachments, and interrupted staging/restore must fail closed and clean up; pin in Task 2.
- Correct snapshot ID with wrong owner/project must reveal no metadata and create no live session; pin in Task 3.
- FTS punctuation/operator input and memory-disabled/rejected indexing must never fail a current prompt or lose the snapshot; pin in Task 4.
- Reload/New Session while task events arrive must not merge old events or history into the new timeline; pin in Task 5.

---

### Task 1: Restore live single-model and all-model execution

**Files:**
- Modify: `web_app/model_compatibility.py`
- Modify: `web/app.js`
- Modify: `web/model_runs.js`
- Modify: `test_model_compatibility.py`
- Modify: `test_web_model_runs_client.py`
- Modify: `test_web_static.py`

**Interfaces:**
- Produces canonical digest normalization accepting bare 64-hex or `sha256:<64-hex>` and returning only `sha256:<64-hex>`.
- Produces `window.JSONCodrLiveSession.current() -> string | null` and `ensure() -> Promise<string>`.
- Consumes `window.JSONCodrHttpIdentity.mutationHeaders()` for all-model start/cancel mutations.

- [ ] **Step 1: Write failing digest and browser-client regressions**

Assert existing bare-digest compatibility state loads valid and matches live bare/prefixed inventory; digest mismatch remains untested; explicit matching quarantine remains unavailable; eligible downloaded records keep Run enabled; all-model start obtains the page session, sends CSRF mutation headers, and cancel does likewise; 401/403 detail re-enables controls; no all-model code reads `json_codr_session`.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_model_compatibility.py test_web_model_runs_client.py test_web_static.py -v`

Expected: FAIL because bare digests invalidate state and all-model POSTs bypass live-session/identity helpers.

- [ ] **Step 3: Canonicalize transport and stored digest spellings**

Accept either exact spelling, reject every other shape, canonicalize to the prefixed form in memory and future writes, and preserve digest-bound status semantics. Do not weaken quarantine or automatic-routing checks.

- [ ] **Step 4: Expose the page-scoped live-session provider**

Wrap current `sessionId`/`ensureSession()` without introducing a second session authority. This task may retain current persistence until Task 5 removes it; the all-model client must stop accessing local storage immediately.

- [ ] **Step 5: Repair all-model mutation transport**

Await `JSONCodrLiveSession.ensure()` on start; use mutation headers on start/cancel; parse server error detail; restore buttons after failure; keep read-only poll/export behavior.

- [ ] **Step 6: Verify GREEN and commit**

Run: `python -m unittest test_model_compatibility.py test_web_model_runs_client.py test_web_static.py -v`

Run: `node --check web/app.js`

Run: `node --check web/model_runs.js`

Run: `git add web_app/model_compatibility.py web/app.js web/model_runs.js test_model_compatibility.py test_web_model_runs_client.py test_web_static.py`

Run: `git commit -m "fix: restore live model execution"`

### Task 2: Consistent immutable snapshot storage

**Files:**
- Create: `web_app/project_sessions.py`
- Modify: `web_app/models.py`
- Modify: `web_app/workspace.py`
- Modify: `web_app/attachments.py`
- Test: `test_project_sessions.py`
- Test: `test_workspace.py`
- Test: `test_attachments_api.py`

**Interfaces:**
- Consumes: `ProjectRegistry.register()/get()/resolve()` and existing session/attachment/artifact directories.
- Produces: `WorkspaceService.create_session(owner_user_id: str | None = None, project_id: str | None = None)`, `session_lock(session_id: str)`, and models `ProjectSessionSnapshot`, `ProjectSessionSaveRequest`, `ProjectSessionRestoreResult`.
- Produces: `ProjectSessionService.save(session_id, project_id, owner_user_id, title, change_type, keywords)`, `list(project_id, owner_user_id, query="")`, `get(snapshot_id, project_id, owner_user_id)`, and `restore(snapshot_id, project_id, owner_user_id)`.

- [ ] **Step 1: Write failing storage/transaction tests**

Cover complete save, repeated distinct saves, restore to a new ID, messages/attachments/skills/artifacts equivalence, source continuity, owner/project denial, concurrent message/upload/remove consistency, reparse/partial-source rejection, staging cleanup, restore rollback, bounded compaction, reasoning exclusion, and deterministic structural/user keywords.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_project_sessions.py test_workspace.py test_attachments_api.py -v`

Expected: FAIL because the models, lock, and service do not exist.

- [ ] **Step 3: Add owner/project-aware session models and locking**

Advance `SessionRecord.schema_version`, add optional `owner_user_id` and `project_id` for backward compatibility, add per-session reentrant locks around get/save/append/delete, wrap each complete attachment import/update/retry/remove transaction in the same lock, and accept owner/project fields during session creation.

- [ ] **Step 4: Implement storage and safe copying**

Store under `project-sessions/<sha256-project-key>/sessions/<32-hex-snapshot-id>`, validate registered project identity, reject every symlink/reparse point, copy only manifest/originals/extracted/artifacts, digest-validate under the session lock, fsync metadata, atomically promote same-parent staging, and clean abandoned state.

- [ ] **Step 5: Implement deterministic summary and identifiers**

Cap summary at 8,000 characters and retain title/date/objectives/outcomes/statuses/model and attachment/reference labels/warnings. Exclude reasoning/binaries. Normalize and bound optional keywords, and always add snapshot/project/session/change-type/title identifiers plus file/component/model/task/reference identifiers when present.

- [ ] **Step 6: Implement restore transaction**

Allocate a new owner/project-bound live session, copy allowed snapshot trees, replace only its manifest with restored state plus fresh ID/timestamps/restored-from ID, and delete the new session on any failure.

- [ ] **Step 7: Verify GREEN and commit**

Run: `python -m unittest test_project_sessions.py test_workspace.py test_attachments_api.py test_conversation.py -v`

Run: `git add web_app/project_sessions.py web_app/models.py web_app/workspace.py web_app/attachments.py test_project_sessions.py test_workspace.py test_attachments_api.py`

Run: `git commit -m "feat: add immutable project session storage"`

### Task 3: Authenticated project APIs and resolvable references

**Files:**
- Modify: `web_app/app.py`
- Modify: `web_app/conversation.py`
- Modify: `web_app/core/mutation_inventory.py`
- Modify: `test_web_api.py`
- Modify: `test_conversation.py`
- Modify: `test_core_architecture.py`

**Interfaces:**
- Consumes: Task 2 service/models and `MutationAuthorizer.principal()`/`csrf()`.
- Produces: project-bound `POST /api/sessions`, `POST /api/projects/resolve`, `POST /api/projects/{project_id}/sessions`, `GET /api/projects/{project_id}/sessions`, `GET /api/projects/{project_id}/sessions/{snapshot_id}`, and `POST /api/projects/{project_id}/sessions/{snapshot_id}/restore`.
- Produces: project-aware `ConversationService.resolve_reference()` through the existing `ProjectRegistry`.

- [ ] **Step 1: Write failing identity/API/reference tests**

Cover project resolve, owner/project-bound clean session creation, first-prompt binding, save/list/get/restore, source continuity, different restore ID, wrong owner/project 404 with no allocation, invalid IDs, missing sources, browser CSRF rejection, CLI/service bearer success, authenticated GET without CSRF, mutation inventory completeness, restored artifacts, and project-file resolution through the associated registered project.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_web_api.py test_conversation.py test_core_architecture.py -v`

Expected: FAIL with missing routes, project session association, and inventory assignments.

- [ ] **Step 3: Wire existing authorities without duplicate stores**

Lazily use `get_core_runtime()` to obtain the one `ProjectRegistry` and `MemoryStore`; construct one `ProjectSessionService` at `workspace.data_root / "project-sessions"`. Add an authenticated-principal helper based on `MutationAuthorizer`: browser cookie or CLI/service bearer, `session.write` scope for all operations, CSRF only for browser mutations.

- [ ] **Step 4: Add project-scoped handlers and error mapping**

Resolve root to project ID server-side. Save accepts `session_id`, title, change type, and optional keywords. GET routes return only owner/project-scoped metadata/compacted history. Map missing or mismatched scope to 404, unsafe state to 400, and request validation to 422.

- [ ] **Step 5: Bind clean sessions before the first prompt**

Accept a validated `project_id` in `POST /api/sessions`, verify it through the registry, and create the session with authenticated owner/project identity. Preserve an explicit legacy-compatible empty request only for non-history API consumers and never use it from the Workspace browser.

- [ ] **Step 6: Preserve reference authority**

Pass `ProjectRegistry` to `ConversationService`; resolve `project_file` references through `session.project_id`, retain the fixed source-root fallback only for legacy unbound sessions, and keep attachment/artifact resolution session-bound.

- [ ] **Step 7: Register every POST route as `session.write`**

Add project resolve, save, and restore to `mutation_inventory.py`; leave list/get read-only.

- [ ] **Step 8: Verify GREEN and commit**

Run: `python -m unittest test_project_sessions.py test_web_api.py test_conversation.py test_core_architecture.py test_auth.py -v`

Run: `git add web_app/app.py web_app/conversation.py web_app/core/mutation_inventory.py test_web_api.py test_conversation.py test_core_architecture.py`

Run: `git commit -m "feat: expose secure project session APIs"`

### Task 4: FTS indexing and automatic Previous Session History retrieval

**Files:**
- Modify: `web_app/project_sessions.py`
- Modify: `web_app/models.py`
- Modify: `web_app/core/memory.py`
- Modify: `web_app/context.py`
- Modify: `web_app/app.py`
- Modify: `web/conversation_view.js`
- Modify: `test_project_sessions.py`
- Modify: `test_collective_memory.py`
- Modify: `test_context.py`
- Modify: `test_web_api.py`
- Modify: `test_conversation_view.py`

**Interfaces:**
- Consumes: Task 2 snapshots/identifiers and Task 3 authenticated session owner/project fields.
- Produces: `MemoryStore.search_collective(..., kind: str | None = None)`, query-safe project history lookup, `ContextAssembler.build(..., previous_history=())`, and structured `previous_session` `ObjectReference` values in `ContextBuildResult`/results/messages.

- [ ] **Step 1: Write failing indexing/retrieval tests**

Assert save indexes kind `previous_session_history` with owner/project/source/idempotency/`retain_details=false`; disabled/rejected indexing preserves snapshots; exact change/file/component/model/task/user keywords find records; inactive/cross-owner/cross-project records do not; FTS punctuation cannot raise; the first prompt in a new project-bound session and all direct-model/workspace-agent/compatibility paths include only relevant bounded summaries; supplied `previous-session:<snapshot-id>` refs appear in structured response/task/message metadata even when response text contains no citation.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_project_sessions.py test_collective_memory.py test_context.py test_web_api.py -v`

Expected: FAIL because kind-filtered safe search and previous-history assembly do not exist.

- [ ] **Step 3: Add compact-memory projection**

On save, accept only the compact summary (maximum 65,536 characters) with nonempty snapshot source refs and deterministic idempotency. Record indexed/skipped/rejected state in snapshot metadata; revoke best-effort if final promotion fails.

- [ ] **Step 4: Add safe, kind-filtered FTS search**

Normalize prompt terms into quoted FTS tokens, bound count/length/results, filter active owner/project/kind in SQL, and return an empty set on unusable syntax rather than failing inference.

- [ ] **Step 5: Add history context framing and budgets**

Introduce a Previous Session History section marked as untrusted reference data. Include title/change identifiers/keywords/summary/source ref, require relevance and source citation, give current request precedence, and budget it alongside skills/attachments without exceeding the existing maximum.

- [ ] **Step 6: Expose supplied history as structured provenance**

Extend `ObjectReference` with kind `previous_session` and `ContextBuildResult` with exact supplied references. Merge those references into direct chat results, agent task result payloads, and persisted assistant messages; render unavailable history references as safe metadata rather than broken download links.

- [ ] **Step 7: Retrieve history on every applicable prompt path**

For direct model, workspace agent, `/api/chat`, and native compatibility paths, search only when the session has owner/project identity and memory is enabled; otherwise proceed with no history. Do not retrieve a snapshot into itself before it is saved.

- [ ] **Step 8: Verify GREEN and commit**

Run: `python -m unittest test_project_sessions.py test_collective_memory.py test_context.py test_web_api.py -v`

Run: `git add web_app/project_sessions.py web_app/models.py web_app/core/memory.py web_app/context.py web_app/app.py web/conversation_view.js test_project_sessions.py test_collective_memory.py test_context.py test_web_api.py test_conversation_view.py`

Run: `git commit -m "feat: retrieve keyworded previous session history"`

### Task 5: Clean live-session and history UI

**Files:**
- Modify: `web/conversation_view.js`
- Modify: `web/app.js`
- Modify: `web/index.html`
- Modify: `web/app.css`
- Modify as required by the proven unassigned-save contract gap: `web_app/app.py`, `web_app/project_sessions.py`, `web_app/workspace.py`, `test_web_api.py`, `test_project_sessions.py`
- Modify: `test_conversation_view.py`
- Modify: `test_web_static.py`
- Modify: `test_ui_customization.py`

**Interfaces:**
- Consumes: Tasks 1, 3, and 4 routes, live-session provider, and metadata.
- Produces: `ConversationView.reset(sessionId = null)`, clean page session creation, a nested Projects & Sessions Workspace section, an unassigned live-session container, backup/save/archive/clear controls, searchable project history, and restore-to-copy behavior.

- [ ] **Step 1: Write failing client/UI tests**

Assert reset clears messages/task maps/sequences; startup never reads/writes `json_codr_session`; an eligible downloaded model keeps Run enabled with or without a selected project; an unassigned session can run prompts and appears in the Sessions container; backup works without promotion; save uses mutation headers and leaves the timeline; archive saves then resets the live chat; restore adopts only the returned new session; New/Clear prevents old task events from applying; UI exposes a nested Projects & Sessions section plus labelled New/Backup/Save/Archive/Restore/Clear controls and searchable Previous Session History with identifiers/keywords. Pin authenticated identity/CSRF behavior so prompt/export controls do not surface `Authentication required` after a valid Administrator sign-in. Regress `persistSettings()` specifically: its `PATCH /api/settings` must use `JSONCodrHttpIdentity.mutationHeaders(...)`, covering Memory & RAG Save plus Hardware Save profile and Reset to Automatic. Regress the separate Restore CPU `POST /api/hardware/restore-cpu` call with the same mutation headers. Every affected button must report an actionable error and re-enable after success, rejection, or rotated/absent identity. Runtime diagnostics must distinguish the current managed supervisor/ready child from historical stale heartbeat/telemetry, render `observed_at`, and never present days-old `recovery_exhausted` records as a current failure.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_conversation_view.py test_web_static.py test_ui_customization.py -v`

Expected: FAIL because reset/lifecycle/history UI are absent and durable browser session restoration remains.

- [ ] **Step 3: Implement clean per-page session lifecycle**

Initialize `sessionId=null`, remove `json_codr_session` reads/writes, and create once per page without calling restore. If a project is selected, resolve it before creating an owner/project-bound session. Otherwise create an authenticated unassigned session that can run normal prompts and display its current action/discussion counts until it is backed up, assigned/saved, or cleared. Reset active task/plan/response/error/attachment state when starting, clearing, archiving, or restoring another live session.

- [ ] **Step 4: Add Projects & Sessions plus lifecycle controls**

Add a Projects & Sessions section directly beneath Workspace navigation/content. Projects resolves, creates, or selects a registered project from the current workspace root. Sessions always shows the active unassigned or project-bound container and unsaved activity. Backup exports without promotion. Save collects title, change type, and optional keywords, preserves the live timeline, and reports indexing state. Archive performs the same durable save, refreshes Context & Files history, then starts a clean session so archived model responses leave the main chat. New/Clear confirms only with unsaved content. Restore clearly opens a copy and renders only that new session.

- [ ] **Step 5: Add searchable Previous Session History**

Resolve the selected project root to project ID, search/list saved sessions, safely render title/date/change type/identifiers/keywords/models/counts/index state with DOM `textContent`, and refresh after project change/save/archive/restore/new/clear. Unassigned sessions show no project history until explicitly assigned, while exported or archived responses become keyword-searchable Previous Session History in Context & Files.

- [ ] **Step 6: Verify GREEN, syntax, and commit**

Run: `python -m unittest test_conversation_view.py test_web_static.py test_ui_customization.py test_workspace_layout.py -v`

Run: `node --check web/app.js`

Run: `node --check web/conversation_view.js`

Run: `git add web/conversation_view.js web/app.js web/index.html web/styles.css test_conversation_view.py test_web_static.py test_ui_customization.py`

Run: `git commit -m "feat: add clean sessions and searchable project history"`

### Task 6: V1.4.5 release and live proof

**Files:**
- Modify: `README.md`
- Modify: `config/runtime.json`
- Modify: `web/index.html`
- Modify: `web/source-control.html`
- Modify: `test_ui_customization.py`
- Modify: `test_web_static.py`
- Create: `.superpowers/sdd/2026-11-26-project-session-history/progress.md`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: tagged release `V1.4.5` and live browser revision matching its commit.

- [ ] **Step 1: Document lifecycle, search identifiers, and retrieval**

Explain clean sessions, immutable owner/project snapshots, change types and keywords, automatic relevant-history retrieval/source refs, memory policy, restore-to-copy, and retained legacy sessions.

- [ ] **Step 2: Run focused and full release gates**

Run: `python -m unittest test_model_compatibility.py test_web_model_runs_client.py test_project_sessions.py test_conversation_view.py test_conversation.py test_collective_memory.py test_context.py test_web_api.py test_web_static.py test_ui_customization.py test_auth.py test_core_architecture.py -v`

Run: `python -m unittest discover`

Run: `node --check web/app.js`

Run: `node --check web/conversation_view.js`

Run: `git diff --check`

Expected: all PASS with no regressions.

- [ ] **Step 3: Perform live integrated-browser proof**

Verify fresh load empty with Run enabled; submit one single-model prompt; start/cancel Ask All Available Models without 403; save a tagged fix; find it by title/change/file keyword in Context & Files; start clean; restore to a different live ID with equivalent messages/files/artifacts; submit a related prompt and confirm structured `previous-session:` provenance; reload and confirm clean slate.

- [ ] **Step 4: Obtain final whole-change security/reliability review**

Review ownership/project isolation, locks/digests/cleanup, references, FTS safety, memory policy, prompt-injection framing, CSRF inventory, DOM safety, and regressions. Resolve every Critical or Important finding and rerun affected tests.

- [ ] **Step 5: Commit release metadata**

Run: `git add README.md config/runtime.json web/index.html web/source-control.html test_ui_customization.py test_web_static.py docs/superpowers/specs/2026-11-26-project-session-history-design.md docs/superpowers/plans/2026-11-26-project-session-history.md`

Run: `git commit -m "release: publish JSON_CODR V1.4.5"`

- [ ] **Step 6: Tag, push, pull-confirm, activate, and record evidence**

Create annotated `V1.4.5`; push main/tag; fetch and pull fast-forward; confirm local/remote/tag equality; activate the build; open `/?view=workspace&revision=<commit>`; record commits, tests, review, retrieval proof, and activation in `.superpowers/sdd/2026-11-26-project-session-history/progress.md` without touching `.tmp`.
