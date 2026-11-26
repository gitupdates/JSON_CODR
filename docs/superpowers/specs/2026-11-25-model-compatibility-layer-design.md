# Model Compatibility Layer Design

## Intent

JSON_CODR must distinguish a downloaded Ollama artifact from a runnable model, recover a useful base text response when optional model features are unsupported, and use a known local fallback when a requested model cannot load. RNJ-1 is the first concrete case, but the behavior must apply to newly discovered Ollama models without a model-specific code change.

## Goals

- Discover exact Ollama model tags that are not yet in `jury_config.json`.
- Preserve `installed` as a download/presence fact while exposing separate compatibility and runnability state.
- Progressively degrade from structured/reasoning features to a minimal `think:false` text request on the same model.
- Quarantine deterministic load/runtime failures by model digest and use a reviewed base fallback.
- Configure the compatible RNJ-1 alternate as an explicit, auditable artifact candidate.
- Report requested and effective model identity whenever fallback occurs.
- Keep unloadable models out of automatic selection, multi-model runs, VS Code export, and runnable UI counts.

## Non-goals

- Do not claim that an alternate GGUF is byte-identical to the requested artifact.
- Do not automatically download arbitrary unreviewed models.
- Do not use fallback to conceal partial-output failures or combine output from two models.
- Do not grant tools or other capabilities based only on a model's advertised metadata.

## Constraints

- Existing API consumers may continue relying on the `installed` boolean.
- Compatibility state is bound to the Ollama artifact digest; replacing an artifact permits a fresh probe.
- Fallback models come only from the reviewed order in repository configuration.
- A fallback occurs only before usable answer content has been emitted.
- The live Ollama service is loopback-only and remains the inference authority.

## Approaches

### Model-specific RNJ exception

Map `rnj-1:8b` directly to one alternate tag. This repairs the immediate symptom but leaves every future incompatible model to fail in the same way.

### Optimistic retry only

Retry failed requests without structured output or reasoning options. This handles feature mismatches but cannot recover deterministic loader crashes and continues to report downloaded models as runnable.

### Shared progressive compatibility layer — selected

Use a shared compatibility policy and digest-bound state across the browser/API service and native transport. Try the requested artifact with its desired response profile, degrade to a minimal text profile for capability failures, then quarantine deterministic runtime failures and select a reviewed installed baseline. Model records and response evidence expose every transition.

This approach fixes RNJ while creating a reusable compatibility boundary for exact, newly discovered Ollama tags.

## Design

`web_app/model_compatibility.py` owns configuration, candidate ordering, failure classification, digest-bound state, and model-record decoration. `config/model-compatibility.json` declares reviewed base fallbacks and logical-model alternates, including the RNJ-1 Unsloth artifact. State is stored under the application's data root and written atomically.

`OllamaService` uses the layer for inventory and non-streaming compatibility. It lists configured models plus newly discovered exact tags, hides implementation-only alternate tags behind their logical model, retries unsupported response features in base text mode, and falls back only after the requested candidate fails before producing an answer.

`NativeOllamaTransport` uses the same layer for streamed canonical inference. It may retry a different candidate only before content or reasoning is emitted. The completion result names the effective model and records a provider fallback event.

Consumers treat `installed=true, runnable=false` as unavailable for routing while continuing to expose the record for diagnosis. Untested models remain manually selectable and receive their first compatibility result on use. UI copy separates downloaded, verified runnable, and catalogued counts.

## Success criteria

- `rnj-1:8b` can produce an answer through its configured compatible artifact.
- A new unconfigured Ollama tag appears in `/api/models` and can return a base text response.
- Unsupported structured/reasoning options degrade on the same model before substitution.
- A deterministic loader failure quarantines only the matching digest and falls back to a reviewed installed model.
- Requested/effective identity and reason are visible in response evidence and model status.
- Existing supported models retain structured output, streaming, tool routing, and direct selection.
