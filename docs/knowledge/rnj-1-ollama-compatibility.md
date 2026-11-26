# RNJ-1 Ollama compatibility lesson

Status: verified locally on 2026-11-25.

## Finding

The downloaded `rnj-1:8b` Ollama artifact is not a reliable execution target in the tested local runtime. Its advertised sliding-window-attention metadata is incompatible with the loader. Download presence therefore must not be treated as proof that a model is runnable.

The reviewed Apache-2.0 GGUF alternate below loaded and returned a direct response:

`hf.co/unsloth/rnj-1-instruct-GGUF:UD-Q4_K_XL`

Observed alternate digest:

`e8bf7b0b2de7381fae37d0ec55f7f6b268dbe67f77b4075adf6b0b8faaf821ec`

## Resolution

JSON_CODR keeps `rnj-1:8b` as the requested logical model and reports the GGUF tag as the effective model. The mapping is declared in `config/model-compatibility.json`; it is not an unreviewed runtime substitution.

For RNJ-1 and future local models, the shared compatibility layer applies this order:

1. Resolve a configured reviewed alternate, if one is preferred for a known incompatible artifact.
2. Try the desired response profile.
3. If optional structured or reasoning features are unsupported, retry the same artifact with a minimal `think:false` text request.
4. If the local runner resets before any usable output, retry that same artifact with bounded delays of 0.5, 1, 2, and 4 seconds.
5. Quarantine deterministic loader failures by artifact digest and use only a reviewed installed baseline.
6. Never switch models after usable content or reasoning has been emitted.

Every successful response preserves both `requested_model` and `effective_model`. Model inventory keeps download presence (`installed`) separate from verified execution (`runnable` and `compatibility_status`).

## Evidence and implementation references

- Policy: `config/model-compatibility.json`
- Compatibility state and digest binding: `web_app/model_compatibility.py`
- API and streamed retry/fallback behavior: `web_app/ollama_service.py`
- Native streamed compatibility: `web_app/core/native_ollama.py`
- Focused regressions: `test_model_compatibility.py`, `test_web_api.py`, and `test_reasoning.py`
- Design: `docs/superpowers/specs/2026-11-25-model-compatibility-layer-design.md`
- Live compatible-artifact response: `RNJ_COMPAT_OK`

## Recollection boundary

This lesson is indexed in JSON_CODR collective memory as a `verified_lesson`. Retrieval may supply it as evidence for planning and diagnosis, but memory is not an execution, capability, authorization, or publication authority. Runtime policy, current artifact digest, deterministic probes, and current verification results remain authoritative.
