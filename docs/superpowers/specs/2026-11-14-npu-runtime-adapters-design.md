# NPU Runtime Adapters Design

## Intent

Add optional Intel, AMD, and generic Windows acceleration to JSON_CODR without changing the existing Ollama model inventory, request path, configuration, or CPU fallback. Optimized models are separate artifacts served by separate runtime adapters and become selectable only after detection and an isolated generation probe succeed.

## Goals

- Preserve existing Ollama behavior and model names.
- Detect Intel NPU/OpenVINO, AMD Ryzen AI, WinML, and legacy DirectML capabilities.
- Catalog compatible open-source coding-model artifacts with license, source, format, runtime, device, size, and compatibility metadata.
- Install runtime dependencies and model artifacts only after explicit user approval through the existing CLI approval flow.
- Probe each adapter in isolation before allowing activation.
- Route chat through a selected optimized model variant while retaining the same structured JSON_CODR response contract.
- Automatically fall back to the corresponding Ollama model, then Ollama CPU, when an optional adapter fails.
- Include every runnable adapter in the existing benchmark UI.

## Non-goals

- Converting or modifying existing Ollama GGUF files in place.
- Replacing Ollama as the default runtime.
- Claiming that device detection alone means a model is compatible.
- Installing vendor drivers or system firmware automatically.
- Treating DirectML as an NPU runtime; it remains a broad Windows GPU compatibility path.

## Constraints

- OpenVINO, Ryzen AI, WinML, and DirectML use different packages and model artifacts.
- Intel NPU execution requires a compatible Intel NPU driver and OpenVINO model.
- Ryzen AI LLM acceleration requires supported AMD hardware, Ryzen AI software, and an AMD-compatible ONNX Runtime GenAI artifact.
- WinML is preferred for new generic Windows ONNX deployments; DirectML is retained for older systems and broad DirectX 12 GPU support.
- Optional runtime dependencies must be isolated from JSON_CODR's base Python environment so mutually exclusive ONNX Runtime packages cannot conflict.
- A failed probe must never change Ollama environment variables or make the base chat unavailable.

## Approaches considered

### Detection and catalog only

Lowest risk, but does not deliver NPU inference.

### Additive runtime adapters (selected)

Keep Ollama unchanged and add isolated connectors for optimized artifacts. This provides real acceleration with explicit compatibility and reliable fallback.

### Replace Ollama with a unified ONNX runtime

Reduces the number of application-level providers but breaks GGUF compatibility, complicates upgrades, and makes the least portable runtime the new base. Rejected.

## Architecture

### Provider boundary

Introduce an inference provider protocol with operations for health, model discovery, capability reporting, structured chat, probe, and benchmark. The current `OllamaService` remains the default implementation and retains its existing public behavior. New providers are registered alongside it rather than injected into Ollama-specific code.

The first adapters are:

- `openvino`: OpenVINO GenAI with explicit `CPU`, `GPU`, or `NPU` device selection.
- `ryzen_ai`: Ryzen AI ONNX Runtime GenAI execution on supported AMD NPU/hybrid modes.
- `winml`: ONNX Runtime GenAI WinML distribution with automatic execution-provider selection.
- `directml`: ONNX Runtime GenAI DirectML for compatible DirectX 12 GPUs.

Each adapter executes in its own managed environment or sidecar process. The app exchanges a small local JSON request/response envelope with the sidecar. Runtime crashes and dependency conflicts therefore cannot take down Ollama.

### Model identity and compatibility

The existing Ollama name remains unchanged, for example `qwen2.5-coder:0.5b`. An optimized artifact receives a qualified identity such as `openvino/OpenVINO/Qwen2.5-Coder-1.5B-Instruct-fp16-ov` or `ryzen_ai/amd/Qwen2.5-Coder-0.5B-Instruct_rai_1.8.0_m1.0_npu`.

Catalog entries include:

- provider and execution device;
- upstream model family and optional Ollama fallback mapping;
- artifact repository and immutable revision;
- license and source URL;
- quantization, expected disk/RAM requirements, and context limit;
- minimum runtime, OS, driver, and hardware requirements;
- verified status and last probe result.

Only allowlisted catalog sources are offered for one-click installation. Custom local artifacts may be registered manually but are labeled unverified until probed.

### Detection

Detection reports evidence separately:

- physical device names from Windows PnP/CIM;
- installed driver and runtime packages;
- runtime-reported execution devices/providers;
- compatible installed model artifacts;
- isolated probe result.

A backend is `detected` when hardware is visible, `runtime_ready` when its connector starts, `model_ready` when a compatible artifact is present, and `verified` only after successful structured generation. The UI must not collapse these states into a single “supported” label.

### Installation

The Hardware Optimization UI can propose exact installation actions for a connector or catalog model. It uses the existing approved CLI action mechanism and offers Allow once or persisted Allow always according to current policy. Driver and firmware installation remain documentation links because they require vendor installers and elevated system changes.

Downloads go to a dedicated provider/model cache under the JSON_CODR data root. Partial downloads use temporary paths, hashes are checked when published, and a failed install leaves the prior configuration intact.

### Routing and fallback

Existing requests continue to select an Ollama model by default. Selecting a qualified optimized model routes only that request to its provider. The provider must return the existing structured response schema; malformed output follows the same error semantics as Ollama.

On connector or generation failure:

1. quarantine that provider/model pair for the session;
2. retry once using its configured Ollama family fallback when installed;
3. otherwise use the current Ollama CPU-compatible model selection;
4. report the fallback and preserve the original diagnostic for Settings.

No optional provider failure changes `OLLAMA_LLM_LIBRARY`.

### UI and API

Hardware Optimization groups candidates by Ollama, Intel/OpenVINO, AMD Ryzen AI, Windows automatic/WinML, and DirectML. Each row shows hardware, runtime, model, and verification state independently, plus actions to inspect, install, probe, benchmark, disable, or remove.

The model selector shows optimized variants in a separate group and identifies their provider/device. Existing Ollama entries retain their current names and ordering.

Provider/model records and installation state are exposed through typed API objects. Transport handlers remain thin; discovery, installation planning, probing, routing, and fallback live in services.

### Benchmarks

The existing standardized suite accepts qualified provider/model targets. Every accelerated run is paired with an Ollama CPU baseline using the closest mapped model family and equivalent generation settings. Results state when artifacts differ, so speed comparisons are not presented as exact hardware-only comparisons.

## Initial model catalog

Start conservatively with vendor-maintained or upstream artifacts:

- OpenVINO Qwen2.5-Coder 1.5B Instruct OpenVINO IR (Apache-2.0).
- AMD Qwen2.5-Coder 0.5B Instruct Ryzen AI NPU artifact.
- AMD-supported Qwen2.5-Coder 1.5B and 7B variants when an official compatible artifact and license metadata are available.
- User-registered ONNX Runtime GenAI coding models for WinML/DirectML, initially marked unverified.

Catalog metadata is data, not hard-coded inference logic, so additional verified artifacts can be added without changing routing.

## Failure handling and reversibility

- CPU/Ollama is always present and cannot be removed from Hardware Optimization.
- Optional providers can be disabled or removed independently.
- Probe and benchmark processes have timeouts and guaranteed cleanup.
- Failed provider/model pairs are quarantined without affecting other models on the provider.
- Settings retain diagnostics but never store secrets or approval tokens.

## Testing

- Contract tests prove the Ollama service and model list remain unchanged.
- Detector tests cover Intel, AMD, generic NPU, false positives, missing drivers, and partial runtime installations.
- Adapter tests cover health, discovery, structured output, timeout, malformed output, and process failure.
- Router tests prove explicit optimized selection, quarantine, mapped Ollama fallback, and final CPU fallback.
- Installation tests prove approval requirements, isolated environments, atomic downloads, and removal.
- API tests cover typed states and errors.
- Browser verification covers grouped models, detection states, install approval, probe, benchmark, disable, and fallback visibility.

## Rollout

Ship behind an optional “Experimental NPU connectors” setting, off by default. Detection is read-only. Runtime/model installation and activation remain explicit. Promote individual adapters from experimental only after a real-device probe and benchmark are recorded without destabilizing Ollama.
