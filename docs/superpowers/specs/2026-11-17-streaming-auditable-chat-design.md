# Streaming, Auditable Chat Design

## Intent

Turn JSON_CODR's single-result prompt screen into a persistent local conversation that can display complex responses while they are produced, expose observable work for review, and exchange referenced files and artifacts without leaving the chat workflow.

The feature is for users validating privately operated local models. It must distinguish a model's intentionally public reasoning output from hidden internal reasoning and from verified system activity.

## Goals

- Preserve multi-message conversation history per existing JSON_CODR session.
- Stream response text and public reasoning records without waiting for task completion.
- Normalize native provider reasoning fields, supported reasoning tags, and requested public rationales into one versioned JSON_CODR trace.
- Show actual task events, tool calls, commands, file activity, verification, warnings, and model routing as observable work.
- Render references to session attachments, generated artifacts, project files, URLs, skills, tasks, and commands as typed, clickable objects.
- Accept files through browse, folder browse, paste, and drag-and-drop; make originals, previews, generated files, and exports available from the relevant message.
- Export a response or full conversation as human-readable Markdown and a reproducible JSON trace.
- Keep the existing direct-chat fallback and existing attachment/archive APIs functional.

## Non-goals

- Inventing reasoning for providers that returned none.
- Presenting generated rationale as proof of hidden model state.
- Granting file, command, or Git authority through a chat reference.
- Replacing the BORG task/event service with UI-specific execution behavior.
- Sending local prompts, traces, or files to remote services by default.

## Anti-goals

- Fake token streaming produced by splitting a completed response in the browser.
- Generic activity spinners that hide whether work has started or stalled.
- Raw HTML or untrusted Markdown capable of script execution.
- Links that expose arbitrary filesystem paths through an unrestricted HTTP route.
- Provider-specific response handling in the chat UI.

## Constraints

- BORG remains the only execution path. Chat submits commands and renders durable events.
- Public reasoning is model output intended for disclosure. Native reasoning, tag-derived reasoning, and requested rationale are labeled by provenance and never conflated with verified work.
- Existing non-streaming inference providers remain supported through a completed-response adapter.
- Session files remain inside the existing bounded attachment and artifact stores.
- The UI must remain usable when reasoning, tools, references, or artifacts are absent.

## Approaches considered

### Structured public rationale only

Every model is prompted to return assumptions, evidence, analysis steps, uncertainty, verification, and answer fields. This is predictable and portable, but discards useful native reasoning output from models that deliberately expose it.

### Raw reasoning-tag capture

The UI displays provider text such as `<think>...</think>`. This is simple for a few models, but model templates differ, tags can leak into answers, and the result has no stable schema or provenance.

### Hybrid normalization — selected

Provider adapters capture explicitly returned reasoning fields or configured reasoning tags when available. Otherwise, debug mode requests a public structured rationale. All paths normalize into the same JSON_CODR reasoning schema and carry a provenance label. This costs more adapter work but gives broad compatibility without making false native-capability claims.

## Canonical conversation contract

Each stored message has a stable identifier, role, timestamps, status, requested and effective model identifiers, content blocks, typed references, attachment identifiers, generated artifacts, usage metadata, and an optional public reasoning trace.

The trace is versioned and contains ordered entries with:

- kind: assumption, plan, analysis, evidence, uncertainty, verification, or conclusion;
- text;
- provenance: native provider field, configured provider tag, or requested public rationale;
- optional source references;
- sequence and timestamp.

Observable work is not stored inside the reasoning trace. It remains durable BORG task events and is joined to the message by task identifier.

## Streaming flow

1. The client creates a pending user and assistant turn through the existing task command path.
2. BORG records acceptance before provider I/O starts.
3. The inference adapter emits ordered delta events for public reasoning, answer content, references, artifacts, usage, and completion.
4. The existing task WebSocket carries those events. Reconnection resumes after the last durable sequence.
5. The client incrementally renders the active assistant message and task activity.
6. Completion stores the normalized message and export metadata. Non-streaming adapters emit one content delta followed by completion.

No browser-only token simulation is permitted.

## Reference and file behavior

References are typed records rather than embedded filesystem links. Session attachments and artifacts resolve through existing bounded download routes. Project-file references open a safe preview endpoint constrained to the active project root; downloading requires the same boundary check. URLs use normal external-link protections. Missing or moved objects remain visible as unavailable references rather than silently disappearing.

Uploads can be associated with the next user message. Generated artifacts appear on the assistant message that created them. Each message offers applicable preview/download controls. Conversation export includes manifests and references; binary files are included only in an explicitly requested ZIP export.

## Interface

The chat view becomes a conversation timeline with a sticky composer. Each assistant turn contains:

- live answer content;
- a collapsible **Reasoning & rationale** panel labeled with provenance;
- a collapsible **Work activity** panel backed by real BORG events;
- reference chips/cards for files, URLs, tasks, skills, commands, and artifacts;
- response and artifact export controls;
- requested/effective model and completion state.

The current structured summary remains available as a compact overview. Users can enable debug rationale for a turn without changing the global model configuration. Progress indicators name the current real phase and show last-event time rather than continuously animating.

## Errors and recovery

Partial content remains visible after cancellation or failure and is marked incomplete. Reconnect deduplicates events by durable sequence. Invalid reasoning payloads are retained as labeled raw public model output and produce a normalization warning. Failed object downloads show a specific unavailable state. Retry creates a new assistant turn linked to its predecessor; it does not overwrite history.

## Validation

- Contract tests cover message, reasoning, reference, delta, and export schemas.
- Adapter tests prove native, tag-derived, fallback-rationale, and non-streaming behavior without claiming unsupported native reasoning.
- Task-stream tests prove ordered persistence, reconnect replay, cancellation, and completion.
- API tests prove attachment/artifact authorization and bounded project-file references.
- Browser tests prove incremental rendering, history restoration, reference actions, file association, and export.
- Existing direct chat, attachments, artifacts, and BORG task suites remain green.

