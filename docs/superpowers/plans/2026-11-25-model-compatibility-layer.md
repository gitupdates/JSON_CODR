# Model Compatibility Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add digest-bound model compatibility, base-response degradation, and explicit reviewed fallback for RNJ-1 and newly discovered Ollama models.

**Architecture:** A shared `ModelCompatibilityLayer` owns candidate ordering, failure classification, persistent quarantine, and status decoration. Both `OllamaService` and `NativeOllamaTransport` consume it, while routing and UI consumers use `runnable` instead of conflating download presence with execution health.

**Tech Stack:** Python 3.15, asyncio, Ollama Python client and HTTP API, FastAPI, Pydantic, vanilla JavaScript, unittest.

**Spec:** `docs/superpowers/specs/2026-11-25-model-compatibility-layer-design.md`

## Global Constraints

- Preserve the existing `installed` boolean as download/presence compatibility.
- Bind persistent compatibility results to a model digest.
- Use only repository-reviewed base fallback models and configured alternates.
- Never substitute after usable model output has been emitted.
- Always expose requested and effective model identity when fallback occurs.
- Do not stage or modify `.tmp/` or unrelated user files.

## Review Focus

- A changed digest must not inherit an old artifact's quarantine; Task 1 tests digest invalidation.
- A malicious or malformed state file must fail closed without escaping the configured state path; Task 1 tests state validation and atomic replacement.
- An unknown downloaded model must not bypass exact-name resolution or tool verification; Task 2 tests discovery and base-only inference.
- A failure after partial streamed output must not switch models and mix answers; Task 2 tests the partial-output boundary.
- Automatic and multi-model routing must not select `runnable=false` records while retaining untested manual compatibility; Task 3 tests each consumer.

---

### Task 1: Compatibility policy and digest-bound state

**Files:**
- Create: `config/model-compatibility.json`
- Create: `web_app/model_compatibility.py`
- Create: `test_model_compatibility.py`

**Interfaces:**
- Produces: `ModelCompatibilityLayer.load(config_path, state_path)`, `inventory(configured, live)`, `candidates(requested, live)`, `record_success(...)`, `record_failure(...)`, and `classify_failure(error)`.
- Consumes: Ollama inventory mappings containing name/model, digest, size, details, and capabilities.

- [ ] **Step 1: Write failing policy tests**

Test RNJ alternate ordering, unknown exact-model ordering, reviewed fallback selection, digest-scoped quarantine invalidation, malformed-state recovery, and hidden alternate inventory decoration.

- [ ] **Step 2: Run tests to verify RED**

Run: `C:\Python315\python.exe -m unittest test_model_compatibility.py -v`

Expected: FAIL because `web_app.model_compatibility` does not exist.

- [ ] **Step 3: Implement the policy and state store**

Implement the interfaces above with validated repository configuration, bounded error text, atomic state replacement, and no network behavior.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `C:\Python315\python.exe -m unittest test_model_compatibility.py -v`

Expected: all compatibility policy tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat(models): add digest-bound compatibility policy`

### Task 2: API and native inference fallback

**Files:**
- Modify: `web_app/ollama_service.py`
- Modify: `web_app/core/native_ollama.py`
- Modify: `web_app/app.py`
- Modify: `test_web_api.py`
- Modify: `test_core_native_ollama.py`

**Interfaces:**
- Consumes: Task 1 `ModelCompatibilityLayer` candidate and state APIs.
- Produces: decorated `/api/models` records, same-model base-mode retry, and pre-output fallback with requested/effective evidence.

- [ ] **Step 1: Write failing service and native transport tests**

Test discovery of an unconfigured exact tag, structured-option failure degrading to base mode, deterministic RNJ loader failure selecting its alternate or reviewed baseline, successful state recording, and rejection of substitution after partial streamed output.

- [ ] **Step 2: Run tests to verify RED**

Run: `C:\Python315\python.exe -m unittest test_web_api.py test_core_native_ollama.py -v`

Expected: new compatibility assertions fail against current direct-only inference.

- [ ] **Step 3: Integrate the shared layer**

Inject one layer from `create_app`, add staged non-streaming requests in `OllamaService`, and add pre-output candidate fallback in `NativeOllamaTransport` without weakening reviewed digest policy.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `C:\Python315\python.exe -m unittest test_web_api.py test_core_native_ollama.py -v`

Expected: service and native inference tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat(models): add progressive inference fallback`

### Task 3: Truthful routing and UI status

**Files:**
- Modify: `web_app/model_runs.py`
- Modify: `web_app/core/inference_adapter.py`
- Modify: `web_app/app.py`
- Modify: `web/app.js`
- Modify: `test_model_runs.py`
- Modify: `test_web_api.py`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: decorated fields `installed`, `runnable`, `compatibility_status`, `effective_model`, and `fallback_reason`.
- Produces: quarantine-aware automatic selection, multi-model rosters, external model export, and downloaded/runnable/catalogued UI counts.

- [ ] **Step 1: Write failing consumer tests**

Test exclusion of `runnable=false`, retention of manually selectable untested models, VS Code/OpenAI filtering, and status/count rendering contracts.

- [ ] **Step 2: Run tests to verify RED**

Run: `C:\Python315\python.exe -m unittest test_model_runs.py test_web_api.py test_web_static.py -v`

Expected: current consumers include every downloaded model and UI reports installed-only counts.

- [ ] **Step 3: Update consumers and UI**

Use a shared runnable predicate (`installed` and `runnable is not false`) for routing; label quarantined options and show separate downloaded, verified runnable, and catalogued totals.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `C:\Python315\python.exe -m unittest test_model_runs.py test_web_api.py test_web_static.py -v`

Expected: all consumer and UI tests pass.

- [ ] **Step 5: Commit**

Commit message: `fix(models): route only compatible local models`

### Task 4: Integrated RNJ and regression verification

**Files:**
- Modify only if a verified regression requires a test-first correction.

**Interfaces:**
- Consumes: Tasks 1-3 complete compatibility behavior.
- Produces: live evidence for RNJ alternate, generic base response, API status, and browser-visible model state.

- [ ] **Step 1: Install the reviewed RNJ alternate**

Run: `ollama pull hf.co/unsloth/rnj-1-instruct-GGUF:UD-Q4_K_XL`

Expected: Ollama records the alternate artifact locally.

- [ ] **Step 2: Exercise direct Ollama and JSON_CODR APIs**

Verify a bounded RNJ response, an ordinary reviewed-model response, `/api/models` requested/effective fields, and fallback evidence.

- [ ] **Step 3: Run the full repository suite and static checks**

Run: `C:\Python315\python.exe -m unittest discover -v`, `node --check web/app.js`, and `git diff --check`.

Expected: zero regressions attributable to this change; any pre-existing failure is named with evidence.

- [ ] **Step 4: Commit verified corrections, if any**

Commit message: `test(models): verify compatibility fallback`
