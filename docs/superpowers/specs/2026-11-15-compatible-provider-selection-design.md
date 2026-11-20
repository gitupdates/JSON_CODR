# Compatible Provider Installation and Selection

## Intent

Install the OpenVINO, Ryzen AI, and WinML optional provider environments without changing the base Ollama runtime. After an Optimization scan or **Test and use**, JSON_CODR should choose a model/backend pair that is proven stable on the current machine, then prefer the fastest result among the compatible candidates.

## Goals

- Manage OpenVINO, Ryzen AI, WinML, and DirectML in separate Python 3.11/3.12 environments.
- Report installation failures per provider without disrupting Ollama or other providers.
- Require environment health, hardware availability, model presence, repeated successful inference, and valid responses before a candidate is eligible.
- Rank eligible candidates by measured throughput, using completion time as the deterministic tie-breaker.
- Save and visibly report the selected model/backend pair after a scan or **Test and use**.
- Fall back to the selected Ollama model in CPU-compatible mode when no optional candidate passes.

## Non-goals and anti-goals

- Do not install or change hardware drivers automatically.
- Do not treat package installation or hardware detection alone as proof that a provider works.
- Do not select a faster candidate that crashes, times out, produces invalid results, or fails repeated runs.
- Do not modify Ollama's installation, model store, or default compatibility behavior.

## Approach

Use compatibility-gated benchmark selection. Each optional provider is installed and probed independently. A candidate must complete all standardized test repetitions successfully with consistent provider/model identity and usable output. Failed candidates remain visible for diagnostics but cannot be selected. Among candidates passing every gate, JSON_CODR selects the highest measured token throughput, with lowest total latency breaking ties. Ollama CPU participates as the guaranteed compatibility baseline and remains selected if every accelerated candidate fails.

Weighted scoring was rejected because partial reliability must never be offset by speed. A fixed provider priority was rejected because actual behavior differs across machines and drivers.

## User flow

The installation controls create or reuse each provider environment and display its exact status. Optimization scan discovers installed runtimes, hardware, and available compatible models. **Test and use** runs the compatibility gate for the chosen target and comparison candidates. On completion, the UI shows which model/backend was selected, why it won, which candidates were rejected, and their failure reasons. Selection is persisted and used for later requests; users can still choose another model or return to automatic/Ollama compatibility mode.

## Constraints

- Provider package wheels must support the installed Python 3.11 or 3.12 interpreter.
- Provider-specific optimized model artifacts are distinct from Ollama GGUF models and may require additional downloads.
- A provider environment may install successfully while remaining ineligible because hardware, drivers, or a compatible model artifact are absent.
- Existing benchmark history remains readable, and existing Ollama-only installations continue to work unchanged.

## Verification

Tests will cover independent provider installation proposals, failure isolation, compatibility-gate rejection, deterministic performance selection, persisted selection, and Ollama fallback. Focused API/UI tests and the full Python suite will run before the local service is restarted and exercised through the live page.
