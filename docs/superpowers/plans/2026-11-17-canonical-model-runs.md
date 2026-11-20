# Canonical Model Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an additive multimodal, one-prompt-to-all-installed-models search while preserving independent single-model chat and normalizing both paths into one auditable response contract.

**Architecture:** A `ModelRunService` snapshots the installed/available roster, persists a run before inference, fans work through the existing core inference boundary under a semaphore, captures immutable provider output, and derives normalized results. Existing `/api/chat` remains backward compatible and links its result to the same canonical contract; a separate batch UI displays all model results without replacing the active-model selector.

**Tech Stack:** Python 3.15, FastAPI, Pydantic, asyncio, existing JSON_CODR core task/inference services, vanilla JavaScript/CSS, unittest.

**Spec:** `docs/superpowers/specs/2026-11-17-canonical-model-runs-design.md`

## Global Constraints

- The existing active-model selector and independent chat remain available and backward compatible.
- Batch mode automatically snapshots every installed and available LLM; the client does not enumerate models.
- Batch prompts may contain text, pasted content, documents, archives, and images.
- Each model receives only supported representations, recorded in its input manifest.
- Original provider output is immutable and separate from normalized fields.
- Server code owns identity, status, timing, errors, normalization, and metrics.
- Default concurrency is two and always bounded by server policy.
- One model failure never discards another model's result.
- Consensus synthesis is available only for the explicit `code_jury` profile and never replaces individual results.
- Code-jury scores are model opinions; the server owns validation, arithmetic mean, threshold verdict, and provenance.

## Review Focus

- The installed-model roster changes during a run: persist and render the submission-time snapshot without adding or losing rows.
- A text-only model receives an image attachment: run with extracted/OCR text and an explicit omission warning, never a false vision claim.
- Cancellation races with completion: retain any committed completion and prevent queued work from starting.
- Original output is large or malformed: preserve its digest/content while polling remains bounded and normalization reports warnings.
- Reused idempotency key has different prompt or attachments: return conflict instead of reusing or starting a second run.

---

### Task 1: Canonical contracts and deterministic normalization

**Files:**
- Modify: `web_app/models.py`
- Create: `web_app/model_run_normalizer.py`
- Create: `test_model_run_normalizer.py`

**Interfaces:**
- Produces: `CanonicalModelRun`, `CanonicalModelResult`, `OriginalModelOutput`, `ModelInputManifest`, `ModelRunCreateRequest`, `JurorVerdict`, `ConsensusVerdict`, and `normalize_model_result(original: OriginalModelOutput, result: ChatResult | None, *, warnings: list[str], timing: ModelTiming) -> CanonicalModelResult`.

- [ ] **Step 1: Write failing contract tests** proving versioned round-trip serialization, forbidden extra fields, stable SHA-256 digesting, distinct original/normalized content, existing `ReasoningTrace` reuse, empty fields instead of invented filler, 1–10 juror score validation, and immutable consensus provenance.
- [ ] **Step 2: Run `C:\Python315\python.exe -m unittest test_model_run_normalizer.py -v`** and verify failures identify missing contracts and normalizer.
- [ ] **Step 3: Implement the contracts and deterministic normalizer**; summary is the existing structured summary or the bounded first meaningful answer line, evidence only accepts typed supplied/provider references, and every derived record carries normalizer version `1`.
- [ ] **Step 4: Rerun the focused test** and verify it passes.
- [ ] **Step 5: Commit** with `feat(models): add canonical model run contracts`.

### Task 2: Durable run store, status aggregation, and idempotency

**Files:**
- Create: `web_app/model_run_store.py`
- Create: `test_model_run_store.py`

**Interfaces:**
- Consumes: Task 1 contracts.
- Produces: `ModelRunStore.create(request, roster, request_key)`, `get(run_id)`, `append_original(run_id, result_id, original)`, `update_result(run_id, result)`, `request_cancel(run_id)`, and `find_by_request_key(session_id, request_key, fingerprint)`.

- [ ] **Step 1: Write failing store tests** for restart-safe reads, stable roster order, atomic original writes, aggregate states, session-scoped idempotent replay, mismatched-key conflict, cancellation/completion races, and session deletion cleanup.
- [ ] **Step 2: Run `C:\Python315\python.exe -m unittest test_model_run_store.py -v`** and verify failure is the absent store.
- [ ] **Step 3: Implement atomic JSON persistence** beneath the existing workspace data root, with replace-on-write manifests and content-addressed original-output files; derive status centrally from result states.
- [ ] **Step 4: Rerun the focused test** and verify it passes.
- [ ] **Step 5: Commit** with `feat(models): persist canonical model runs`.

### Task 3: Capability-aware all-model batch execution

**Files:**
- Create: `web_app/model_runs.py`
- Create: `test_model_runs.py`
- Modify: `web_app/context.py`

**Interfaces:**
- Consumes: `ModelRunStore`, `ContextAssembler`, installed model listing, vision capability checks, and the existing core inference submission function.
- Produces: `ModelRunService.create(request) -> CanonicalModelRun`, `run(run_id) -> None`, `cancel(run_id) -> CanonicalModelRun`, `get(run_id) -> CanonicalModelRun`, and `recover_incomplete_runs() -> None`.

- [ ] **Step 1: Write failing service tests** proving all installed/available models are snapshotted automatically, unavailable configured models are reported but not executed, concurrency never exceeds two, output order follows the roster, partial failures persist, one prompt reaches every roster model, and restart recovery converts abandoned queued/running results into honest `failed` results with code `server_restart` while retaining captured output.
- [ ] **Step 2: Add failing multimodal and jury tests** proving vision models receive original supported images, text-only models receive extracted/OCR context plus omission warnings, a model is `unsupported` only when no usable representation exists, and `code_jury` sends identical review criteria to every roster model.
- [ ] **Step 3: Run `C:\Python315\python.exe -m unittest test_model_runs.py -v`** and verify failures identify the missing service.
- [ ] **Step 4: Implement `ModelRunService`** using `asyncio.Semaphore(2)` and the existing inference/task boundary; persist queued/running/terminal transitions and capture original events before normalization.
- [ ] **Step 5: Rerun the focused test** and verify it passes.
- [ ] **Step 6: Commit** with `feat(models): run one prompt across installed models`.

### Task 4: Deterministic jury validation and bounded synthesis

**Files:**
- Create: `web_app/model_jury.py`
- Create: `test_model_jury.py`

**Interfaces:**
- Consumes: canonical results and original outputs from Tasks 1–3.
- Produces: `validate_juror_result(result) -> JurorVerdict | JuryValidationError` and `build_consensus(verdicts, failures, synthesizer) -> ConsensusVerdict`.

- [ ] **Step 1: Write failing jury tests** for valid and malformed juror JSON, preserved invalid originals, arithmetic mean, PASS/CONDITIONAL_PASS/FAIL thresholds, critical-issue override, complete provenance, synthesizer fallback, and total synthesis failure that retains deterministic consensus data.
- [ ] **Step 2: Run `C:\Python315\python.exe -m unittest test_model_jury.py -v`** and verify failures identify the missing jury service.
- [ ] **Step 3: Implement jury validation and consensus**; server arithmetic and verdict are immutable, while the synthesizer may only populate agreed issues, dissent, and rationale.
- [ ] **Step 4: Rerun the focused test** and verify it passes.
- [ ] **Step 5: Commit** with `feat(models): add auditable code jury consensus`.

### Task 5: Polling, originals, cancellation, exports, search, and single-chat linkage

**Files:**
- Modify: `web_app/app.py`
- Modify: `web_app/conversation.py`
- Modify: `test_web_api.py`

**Interfaces:**
- Consumes: `ModelRunService` and Task 1 contracts.
- Produces: `POST /api/model-runs`, `GET /api/model-runs/{run_id}`, `GET /api/model-runs/{run_id}/results/{result_id}/original`, `POST /api/model-runs/{run_id}/cancel`, `GET /api/model-runs/{run_id}/export`, and run linkage on `/api/chat`.

- [ ] **Step 1: Extend existing API tests first** for queued creation, roster-free client requests, `general` and `code_jury` profiles, bounded polling payloads, authorized original retrieval, cancellation, JSON/Markdown/CSV exports, original-versus-normalized search provenance, consensus provenance, and mismatched idempotency conflict.
- [ ] **Step 2: Add failing compatibility assertions** proving existing single-model `/api/chat` fields remain unchanged while a canonical `run_id` is added and persisted.
- [ ] **Step 3: Run only the new/extended `test_web_api.py` cases** and verify they fail for absent routes/linkage.
- [ ] **Step 4: Implement thin FastAPI handlers** that validate input, call `ModelRunService`, map domain errors, and never perform inference or persistence in handlers.
- [ ] **Step 5: Add deterministic exporters and scoped search**; full originals remain behind the separate authorized endpoint.
- [ ] **Step 6: Rerun the focused API cases** and verify they pass.
- [ ] **Step 7: Commit** with `feat(api): expose canonical all-model runs`.

### Task 6: Shared CLI and additive all-model search UI

**Files:**
- Modify: `web/index.html`
- Create: `web/model_runs.js`
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Create: `model_jury_cli.py`
- Create: `test_model_jury_cli.py`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: Task 4 endpoints.
- Produces: a separate “All models” search surface and a thin CLI for `--file`, `--code`, or stdin; both call the canonical service path, while the existing active-model selector and “Run model” form remain intact.

- [ ] **Step 1: Add failing static contract tests** for the separate all-model prompt, General/Code Jury profile selector, shared attachment/session context, start/cancel controls, accessible live status, stable per-model result rows, jury consensus panel, original-output links, filtering, and export controls; assert the existing `chat-form` and active-model selector remain present.
- [ ] **Step 2: Run `C:\Python315\python.exe -m unittest test_web_static.py -v`** and verify the new assertions fail.
- [ ] **Step 3: Implement `model_runs.js`** to create a run, poll with one in-flight request, update only changed rows, preserve roster order, stop polling at terminal status, and surface partial failures without hiding successes.
- [ ] **Step 4: Add responsive UI and navigation** without continuous animations or unbounded DOM growth.
- [ ] **Step 5: Run the static test and `node --check web/model_runs.js && node --check web/app.js`** and verify both pass.
- [ ] **Step 6: Write failing CLI tests** proving file, inline code, and stdin create the same `code_jury` request and poll/export the same run rather than implementing Ollama calls independently.
- [ ] **Step 7: Implement the thin CLI, run `C:\Python315\python.exe -m unittest test_model_jury_cli.py -v`, and verify it passes.**
- [ ] **Step 8: Commit** with `feat(web): add multimodal all-model jury search`.

### Task 7: Integrated verification with real installed models

**Files:**
- Modify only if verification exposes a tested defect.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: live evidence that one prompt reaches the persisted installed roster and that independent chat still works.

- [ ] **Step 1: Run `C:\Python315\python.exe -m unittest discover -v`** and require zero failures.
- [ ] **Step 2: Run Python compilation and JavaScript syntax checks** for all changed modules.
- [ ] **Step 3: Restart the exact JSON_CODR server process** and verify health without killing unrelated processes.
- [ ] **Step 4: In the visible browser, upload real code, text, and image context, submit General and Code Jury all-model prompts, and verify every submission-time installed model receives a persistent row with honest capability adaptations and original-output access.**
- [ ] **Step 5: Verify jury arithmetic, threshold verdict, individual verdict retention, synthesizer identity/fallback, and consensus provenance against the live results.**
- [ ] **Step 6: Reload the page and verify the batch run persists; then run the existing active-model chat independently and verify it remains functional.**
- [ ] **Step 7: Verify JSON, Markdown, and CSV exports against the displayed run and inspect browser console errors.**
- [ ] **Step 8: Run the CLI against a real file and verify it returns the same persisted run schema.**
- [ ] **Step 9: Commit any test-proven verification fixes separately; otherwise record completion against the prior commit.**
