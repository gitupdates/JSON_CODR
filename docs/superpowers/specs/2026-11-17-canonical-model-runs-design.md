# Canonical model runs design

## Intent

Give JSON_CODR one durable reporting contract for both multi-model evaluation and ordinary single-model chat. Users can submit one multimodal search prompt that automatically runs against every installed and available LLM, watch and poll the run, compare all normalized results in one view, and retain each provider's original response for audit, search, and citation.

## Goals

- Add a versioned, server-owned model-run envelope.
- Support a batch mode that executes one prompt against all installed and available models with bounded concurrency.
- Normalize ordinary single-model results through the same per-model result contract.
- Preserve immutable original provider output separately from normalized fields.
- Record requested and effective model identities, status, timing, reasoning, evidence, warnings, references, and errors consistently.
- Allow completed, partial, failed, or cancelled runs to be polled and exported.
- Accept text, pasted content, documents, archives, and images in the same batch prompt while treating one-prompt-to-all-models fan-out as the defining behavior.
- Record the exact input representation delivered to each model so capability adaptation cannot be mistaken for equivalent multimodal processing.
- Offer an on-demand `code_jury` profile that validates one technical verdict per completed model and then produces a separately identified consensus record.

## Non-goals

- Do not force models to generate trustworthy metrics or schema metadata.
- Do not treat normalized text as a replacement for the original response.
- Do not claim that every selected model supports vision; unsupported inputs are reported per model.
- Do not rank answer quality without a separate evaluation method.
- Do not present juror scores or synthesized conclusions as objective benchmark measurements.

## Anti-goals

- A single model failure must not discard other results.
- Prompt instructions must not be the only schema enforcement mechanism.
- Batch execution must not start an unbounded number of models concurrently.
- Parsing failures must not mutate, hide, or discard provider output.

## Chosen approach

Combine a canonical batch evaluation service with server-normalized single-model results.

The batch service owns run identity, lifecycle, model-roster snapshot, concurrency, cancellation, persistence, and polling. At submission it snapshots every model currently reported as installed and available; unavailable configured entries are recorded outside the execution roster rather than invoked. A shared normalizer maps both batch and standard-chat outcomes into the same `CanonicalModelResult` structure. Provider-native output is captured first as immutable `OriginalModelOutput`; normalization produces a separate derived view with provenance and warnings.

Prompt-only JSON alignment was rejected because smaller and older models do not reliably follow output schemas. A batch-only contract was rejected because ordinary chat results would remain incompatible with reports and searches.

## Contracts

`CanonicalModelRun` contains:

- `schema_version`
- `run_id`
- `mode`: `batch` or `single`
- `status`: `queued`, `running`, `completed`, `partial`, `failed`, or `cancelled`
- prompt and context references
- immutable model-roster snapshot
- created, started, and completed timestamps
- ordered `CanonicalModelResult` entries

`CanonicalModelResult` contains:

- requested model and effective model
- an input manifest describing supplied text, extracted documents, original images, omitted modalities, and capability adaptations
- status: `queued`, `running`, `completed`, `timeout`, `failed`, `cancelled`, or `unsupported`
- server-recorded timing and error classification
- immutable original output reference and digest
- normalized summary, answer, reasoning, evidence, warnings, references, and actions
- normalization provenance, version, and confidence/warnings

`OriginalModelOutput` contains the exact received provider content and native reasoning events, provider metadata, content type, digest, and capture timestamps. It is append-only. Derived normalization records point to its digest.

`JurorVerdict` contains a server-validated 1–10 opinion score, critical issues, rationale, juror model identity, and a reference to that model's original output. Invalid structured verdicts remain ordinary canonical results with a jury-validation warning rather than disappearing.

`ConsensusVerdict` contains the deterministic arithmetic mean of valid juror scores, `PASS`, `CONDITIONAL_PASS`, or `FAIL` under the documented thresholds, agreed issues, dissenting notes, a synthesis rationale, synthesizer identity, and provenance for every contributing juror. The original juror results remain authoritative records of what each model said.

## Service flow

1. Validate the prompt, session, attachments, and server concurrency bound, then snapshot all installed and available models.
2. Persist a queued run before inference begins.
3. Resolve every roster model's capabilities independently, including vision, extracted-text, archive, and context compatibility.
4. Build a per-model input manifest: vision-capable models receive supported original images plus extracted text; text-only models receive extracted or OCR text when available and an explicit warning for omitted binary modalities.
5. Execute models through the existing inference boundary under a bounded semaphore.
6. Capture native output and events before normalization.
7. Normalize each outcome with deterministic server code; retain unparsed material and warnings.
8. Persist result transitions so polling never depends on process memory.
9. Derive the overall run status from terminal per-model states.
10. For `code_jury`, validate juror verdicts, compute the arithmetic score and threshold verdict in server code, then request a bounded synthesis narrative from a configured compatible model with explicit fallback; preserve synthesis failure without changing the completed juror records.
11. Expose JSON, Markdown, and CSV exports containing normalized fields, jury/consensus fields when present, and references to original outputs.

Ordinary chat uses the same capture and normalization steps but creates a `single` run internally. Its existing response remains backward compatible while including a run identifier and canonical result.

## API shape

- `POST /api/model-runs` creates a batch run.
- `GET /api/model-runs/{run_id}` returns the current canonical envelope.
- `GET /api/model-runs/{run_id}/results/{result_id}/original` returns the authorized original output.
- `POST /api/model-runs/{run_id}/cancel` requests cancellation.
- `GET /api/model-runs/{run_id}/export?format=json|markdown|csv` exports results.
- Existing `/api/chat` remains supported and returns its established fields plus canonical run linkage.

The create request contains `session_id`, prompt text, attachment identifiers already owned by that session, `profile` (`general` or `code_jury`), the public-reasoning preference, and an optional client request key. The server derives an ordered, deduplicated roster from all models currently reported as installed and available; the client does not need to select each model. Project identity is derived from the session rather than accepted as an independent claim. Provider-specific arbitrary options and caller-selected timeouts are excluded initially; server policy owns resource limits.

Creation is idempotent when supplied a client request key. Keys are scoped to the session and retained with the run. Reuse with the same request fingerprint returns the existing run; reuse with different input returns a conflict. Model order follows the server's stable roster snapshot even when completion order differs.

The batch UI provides one prompt control and one run action. It renders a stable result card or table row for every roster model as results arrive, showing model identity, current status, normalized answer, warnings, timing, and access to original output. Completion order does not reorder the roster. Users can search, filter, expand, and export the complete result set without opening separate chat sessions.

The UI exposes `General search` and `Code jury` profiles. Code jury adds validated juror fields and a consensus panel after juror execution; it never hides individual results. The same service is callable from a thin CLI for file, inline-code, and stdin input so CLI and web behavior cannot diverge.

Original-output metadata and digest are present in polling results, while full original content is retrieved from the separate authorized endpoint to keep polling payloads bounded. Runs and originals follow their owning session's retention and deletion lifecycle.

## Streaming single-model chat

Ordinary streaming chat creates and persists its canonical `single` run before provider execution. The first stream event carries the `run_id`; existing event fields remain backward compatible. Provider events update the run, successful completion finalizes it, and disconnect, timeout, or failure preserves received output with an incomplete terminal result. Non-streaming chat returns the same linkage in its response.

## Original output boundary

“Original” means the provider-native parsed events captured at the adapter boundary plus the exact accumulated native text and reasoning fields before JSON_CODR normalization. Events are serialized deterministically and digested when captured. It does not promise preservation of HTTP framing, transfer encoding, or other transport bytes that the provider client does not expose. Normalization never edits this record.

## Normalization rules

- `summary` and `answer` are strings derived from existing structured fields when present; otherwise the answer is the accumulated provider content and the summary is a bounded deterministic first meaningful line.
- `reasoning` uses the existing typed `ReasoningTrace` and retains provenance.
- `evidence` is a list of typed references to supplied context or provider-emitted citations; prose is not promoted to verified evidence merely because it resembles a citation.
- `warnings` is a list of server-generated strings for parsing, capability, truncation, and normalization issues.
- `references` and `actions` reuse the existing validated contracts.
- Every derived field records the normalizer version. Absence remains empty or null rather than model-invented filler.

## Jury rules

- Every installed and available model in the roster is asked for the same code-review criteria: correctness, edge cases, regressions, and security, plus the user's context requirements.
- Juror JSON is validated server-side. The unmodified response is retained even when validation fails.
- The server computes the arithmetic mean from valid 1–10 scores. `PASS` requires a mean of at least 8.0 and no validated critical issue; `CONDITIONAL_PASS` covers 6.0–7.99 without a severe issue; otherwise the verdict is `FAIL`.
- The synthesizer may consolidate issue wording and explain agreement or dissent, but it cannot change the server-computed score or threshold verdict.
- Synthesis uses an explicitly recorded installed model and fallback order. If all synthesizers fail, the run retains its juror results and deterministic consensus fields with a synthesis warning.
- Consensus provenance lists all included, excluded, invalid, failed, and timed-out jurors.

## Run status aggregation

- `completed`: every requested model completed.
- `partial`: at least one completed and at least one reached another terminal state.
- `cancelled`: no model completed and cancellation affected the run.
- `failed`: no model completed and every result is failed, timed out, or unsupported.
- `running`: at least one result is queued or running and cancellation has not reached a terminal run state.

Cancellation is best effort through the existing task boundary. Queued work becomes cancelled immediately. Running providers are interrupted when their adapter supports it; otherwise their output remains recorded until they reach a terminal state. A completion durably committed before cancellation remains completed. New work never starts after cancellation is committed.

## Search and references

Search indexes original content and normalized fields as separate sources. Matches identify the run, model, source (`original` or `normalized`), and character or event location. References never silently redirect from original material to normalized text.

## Failure behavior

- Timeout and provider errors are terminal per-model results with server-owned codes.
- A model is `unsupported` only when no usable representation of the prompt can be delivered. If text or extracted/OCR content remains usable, the model runs with explicit modality-omission warnings rather than being falsely described as vision-capable.
- Normalization failure preserves the original output and marks normalization warnings.
- A run is `partial` when at least one model completes and at least one does not.
- Cancellation preserves all output received before cancellation.

## Constraints and builder decisions

- Reuse the existing core inference/task boundary rather than call Ollama from HTTP handlers.
- Persist runs in the existing workspace/task data path before adding another database authority.
- Default concurrency is two and remains bounded by a small server maximum.
- No hidden model is used to normalize results in the first implementation; deterministic server extraction avoids recursive cost and hallucinated interpretation.
- Raw output access follows the same session and project authorization as the originating prompt.

## Verification

- Contract tests cover stable serialization and backward compatibility.
- Service tests prove bounded concurrency, ordered results, partial failure, cancellation, and restart-safe polling.
- Tests prove original output remains byte-for-byte stable when normalization succeeds or fails.
- API tests cover multimodal compatibility, exports, and authorization.
- A live Ollama acceptance pass runs one prompt against multiple installed models and compares persisted results after reload.
