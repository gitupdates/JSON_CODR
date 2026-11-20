# NPU Runtime Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in OpenVINO, Ryzen AI, WinML, and DirectML model connectors while preserving the existing Ollama request path and CPU fallback.

**Architecture:** Keep `OllamaService` as the default provider and introduce a registry of isolated sidecar-backed providers for optimized artifacts. Hardware, runtime, artifact, and probe states remain distinct; qualified optimized models route explicitly and fall back through a mapped Ollama model without mutating Ollama configuration.

**Tech Stack:** Python 3, FastAPI, Pydantic, asyncio subprocesses, OpenVINO GenAI, ONNX Runtime GenAI, WinML, DirectML, AMD Ryzen AI, vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-11-14-npu-runtime-adapters-design.md`

## Global Constraints

- Existing Ollama model names, configuration, chat behavior, and `OLLAMA_LLM_LIBRARY` handling must remain unchanged.
- Optional runtime packages must use isolated managed environments or sidecars.
- Hardware detection is read-only; installs and activation require explicit approval.
- An optimized model is selectable only after its provider, device, artifact, and isolated structured-generation probe succeed.
- Failure falls back to the mapped Ollama model and then the current Ollama CPU-compatible selection.
- DirectML is a Windows GPU compatibility backend, not an NPU backend; WinML is preferred for new generic Windows deployments.
- Vendor drivers and firmware are never automatically installed.

## Review Focus

- A physical NPU with no usable driver/runtime must be reported as detected but not runnable; pin in Task 2 detector tests.
- Conflicting ONNX Runtime Python distributions must never share the base environment; pin in Task 3 environment-planning tests.
- A connector process that exits, times out, or emits malformed JSON must be quarantined without affecting Ollama; pin in Tasks 3 and 5.
- A catalog artifact whose family fallback is absent from Ollama must use the current CPU-compatible Ollama selection and report that fallback; pin in Task 5.
- Benchmarks comparing different artifacts must label the comparison as model-variant rather than hardware-only; pin in Task 6.

---

### Task 1: Provider and model contracts

**Files:**
- Create: `web_app/inference/contracts.py`
- Create: `web_app/inference/catalog.py`
- Create: `test_inference_contracts.py`
- Modify: `web_app/models.py`

**Interfaces:**
- Produces: `ProviderKind`, `ProviderState`, `OptimizedModelRecord`, `ProbeResult`, `InferenceProvider` protocol, and `OptimizedModelCatalog.list()`/`get(model_id)`.
- Consumes: existing `ChatResult` and structured response schema.

- [ ] **Step 1: Write failing contract and catalog tests**

Add tests named `test_qualified_model_ids_do_not_collide_with_ollama_names`, `test_catalog_exposes_initial_vendor_models_with_license_and_fallback`, and `test_catalog_rejects_duplicate_or_unqualified_ids`. Assert initial entries for the OpenVINO Qwen2.5-Coder 1.5B artifact and AMD Qwen2.5-Coder 0.5B artifact include provider, source URL, license, revision, device, format, requirements, and Ollama fallback mapping.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest test_inference_contracts -v`

Expected: FAIL because `web_app.inference` does not exist.

- [ ] **Step 3: Implement contracts and immutable catalog**

Create typed records and an `InferenceProvider` protocol with `health()`, `list_models()`, `probe(model)`, `chat(model, prompt, images=None)`, and `benchmark(model, prompts, repeats)`. Model IDs use `<provider>/<repository-or-local-id>` and never reuse Ollama names.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest test_inference_contracts -v`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit**

```bash
git add web_app/inference web_app/models.py test_inference_contracts.py
git commit -m "feat(inference): define optimized provider contracts"
```

### Task 2: Vendor-aware hardware and runtime detection

**Files:**
- Create: `web_app/inference/detection.py`
- Create: `test_inference_detection.py`
- Modify: `web_app/hardware.py`
- Modify: `test_hardware.py`

**Interfaces:**
- Consumes: `ProviderKind`, `ProviderState` from Task 1.
- Produces: `AcceleratorDetector.detect() -> list[ProviderState]` with separate `hardware_detected`, `runtime_ready`, `model_ready`, `verified`, `evidence`, and `reason` fields.

- [ ] **Step 1: Write failing Intel, AMD, WinML, and DirectML detection tests**

Cover Intel AI Boost plus OpenVINO `NPU`, AMD Ryzen AI plus Ryzen AI runtime, generic NPU without provider, Windows 11 24H2 WinML, DirectX 12 DirectML, missing driver/runtime, duplicate PnP names, and false-positive input devices. Assert DirectML is `gpu`, not `npu`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest test_inference_detection test_hardware -v`

Expected: FAIL because vendor provider states are unavailable.

- [ ] **Step 3: Implement injectable detection probes**

Implement detector inputs for PnP devices, OS build, commands/packages, and provider-reported devices. Adapt `HardwareBackendManager.detect()` to merge legacy Ollama backends with provider states without changing existing CPU/CUDA/ROCm/Vulkan records.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest test_inference_detection test_hardware -v`

Expected: all detection and legacy hardware tests pass.

- [ ] **Step 5: Commit**

```bash
git add web_app/inference/detection.py web_app/hardware.py test_inference_detection.py test_hardware.py
git commit -m "feat(hardware): detect NPU runtime readiness"
```

### Task 3: Isolated connector environments and sidecar protocol

**Files:**
- Create: `web_app/inference/environments.py`
- Create: `web_app/inference/sidecar.py`
- Create: `web_app/inference/sidecar_main.py`
- Create: `test_inference_sidecar.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: provider/model contracts from Task 1.
- Produces: `EnvironmentManager.plan(provider)`, `install_command(provider)`, `remove(provider)`, and `SidecarClient.request(operation, payload, timeout)`.

- [ ] **Step 1: Write failing isolation and protocol tests**

Test that each provider resolves to a different data-root environment, base requirements remain free of mutually exclusive runtime packages, install plans contain pinned provider-specific packages, stdout JSON is parsed, stderr is diagnostic only, and exit/timeout/malformed JSON produce typed failures with process cleanup.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest test_inference_sidecar -v`

Expected: FAIL because environment and sidecar services do not exist.

- [ ] **Step 3: Implement environment planning and local JSON sidecar transport**

Use `sys.executable -m venv` under the JSON_CODR data root and one newline-delimited JSON request/response per sidecar invocation. Do not install packages from application code in this task; return commands for the existing approval queue.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest test_inference_sidecar -v`

Expected: all Task 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add web_app/inference/environments.py web_app/inference/sidecar.py web_app/inference/sidecar_main.py test_inference_sidecar.py requirements.txt
git commit -m "feat(inference): isolate accelerator connectors"
```

### Task 4: OpenVINO, Ryzen AI, WinML, and DirectML adapters

**Files:**
- Create: `web_app/inference/providers/openvino.py`
- Create: `web_app/inference/providers/onnx_genai.py`
- Create: `web_app/inference/providers/registry.py`
- Create: `test_inference_providers.py`

**Interfaces:**
- Consumes: `InferenceProvider`, catalog records, `SidecarClient`, and detected provider state.
- Produces: `ProviderRegistry.get(provider)`, `available()`, and adapters implementing the Task 1 protocol.

- [ ] **Step 1: Write failing adapter tests**

Using a fake sidecar transport, assert OpenVINO selects only declared `CPU`/`GPU`/`NPU`, Ryzen AI selects its declared NPU/hybrid mode, WinML requests automatic provider selection, DirectML requests `DML`, unsupported model/provider combinations are rejected before launch, and successful probes require a valid structured `ChatResult`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest test_inference_providers -v`

Expected: FAIL because provider adapters do not exist.

- [ ] **Step 3: Implement thin sidecar-backed adapters and registry**

Keep vendor imports inside `sidecar_main.py` provider handlers so the JSON_CODR process never imports optional runtime packages. Normalize all successful responses into existing `ChatResult` fields.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest test_inference_providers -v`

Expected: all Task 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add web_app/inference/providers test_inference_providers.py
git commit -m "feat(inference): add NPU runtime adapters"
```

### Task 5: Explicit routing, quarantine, and Ollama fallback

**Files:**
- Create: `web_app/inference/router.py`
- Create: `test_inference_router.py`
- Modify: `web_app/app.py`
- Modify: `web_app/ollama_service.py`
- Modify: `test_web_api.py`

**Interfaces:**
- Consumes: `ProviderRegistry`, `OptimizedModelCatalog`, current `OllamaService`, and workspace settings.
- Produces: `InferenceRouter.list_models()`, `chat(model, prompt, images=None)`, `probe(model)`, and persistent per-provider/model status.

- [ ] **Step 1: Write failing routing and backward-compatibility tests**

Assert unqualified model requests call only the existing Ollama service; qualified models call only their adapter; adapter timeout, exit, and malformed output quarantine only that pair; mapped fallback uses the installed Ollama family; absent mapping uses current CPU-compatible Ollama selection; fallback is reported; optional failures never write `OLLAMA_LLM_LIBRARY`; existing Ollama API payloads remain identical.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest test_inference_router test_web_api -v`

Expected: new routing tests fail while existing Ollama tests pass.

- [ ] **Step 3: Implement router and thin API integration**

Construct the router beside `OllamaService`; route `/api/models`, `/api/chat`, provider probe, and provider status through it. Do not alter `OllamaService.chat()` semantics; only add narrowly required read-only helpers for fallback resolution if tests require them.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest test_inference_router test_web_api -v`

Expected: all routing and API tests pass.

- [ ] **Step 5: Commit**

```bash
git add web_app/inference/router.py web_app/app.py web_app/ollama_service.py test_inference_router.py test_web_api.py
git commit -m "feat(chat): route optional optimized models safely"
```

### Task 6: Installation approval, UI, benchmarks, and end-to-end verification

**Files:**
- Modify: `web_app/actions.py`
- Modify: `web_app/hardware.py`
- Modify: `web_app/app.py`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/app.css`
- Modify: `test_actions.py`
- Modify: `test_hardware.py`
- Modify: `test_web_api.py`
- Modify: `test_web_static.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: environment plans, provider states, catalog, router, and existing approval queue.
- Produces: connector/model install proposals; grouped Hardware Optimization and model-selector UI; provider-aware benchmarks and removal/disable actions.

- [ ] **Step 1: Write failing approval, API, benchmark, and static UI tests**

Assert connector/model installs enter the existing approval flow, no driver install is proposed, removal is reversible, model selectors group optimized variants separately, all four connectors expose independent states, and cross-artifact benchmarks set `comparison_kind` to `model_variant` rather than `hardware_only`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest test_actions test_hardware test_web_api test_web_static -v`

Expected: FAIL because install proposals and provider-aware UI/benchmarks are absent.

- [ ] **Step 3: Implement install planning and provider-aware benchmarks**

Reuse the existing action approval service. Store artifacts below the data root, use temporary download paths plus atomic rename, and preserve provider/model diagnostics on failure.

- [ ] **Step 4: Implement grouped, reversible UI controls**

Add the experimental setting, provider sections, state details, inspect/install/probe/benchmark/disable/remove controls, and qualified model options without renaming or reordering current Ollama options.

- [ ] **Step 5: Run focused tests and syntax checks**

Run: `python -m unittest test_actions test_hardware test_inference_contracts test_inference_detection test_inference_sidecar test_inference_providers test_inference_router test_web_api test_web_static -v`

Run: `node --check web/app.js`

Expected: all focused tests pass and JavaScript syntax check exits 0.

- [ ] **Step 6: Run the project test suite**

Run: `python -m unittest discover -v`

Expected: all tests pass with no errors.

- [ ] **Step 7: Verify in the live browser**

Start the existing JSON_CODR server using its tracked launcher PID. Verify existing Ollama chat first, then detection states, an unavailable-connector explanation, approval proposal, successful probe when local hardware permits, benchmark labels, disable/remove, and automatic fallback. Never require a vendor runtime to pass on unsupported hardware.

- [ ] **Step 8: Commit**

```bash
git add web_app web test_actions.py test_hardware.py test_web_api.py test_web_static.py README.md
git commit -m "feat(web): manage optional NPU connectors"
```

## Self-review

- Spec coverage: provider isolation, detection evidence, catalog, install approval, routing, fallback, benchmarks, reversibility, and experimental rollout each map to Tasks 1–6.
- Step scan: every production step follows a named failing test and has a focused verification command.
- Type consistency: Tasks 2–6 consume the Task 1 provider/model contracts; all adapters use the Task 3 sidecar interface and Task 4 registry.
- Review focus: each listed failure mode has a named test location.
- Proportion: shared contracts and interfaces are specified; implementation bodies remain with the executor.
