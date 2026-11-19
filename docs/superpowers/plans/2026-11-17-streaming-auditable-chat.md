# Streaming, Auditable Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent JSON_CODR conversation UI with genuine model streaming, provenance-labeled public reasoning, observable BORG work, typed object references, and message/session file export.

**Architecture:** Extend the canonical models first, then make BORG task execution asynchronous so adapter deltas reach the existing task WebSocket while inference is running. Normalize provider-native reasoning, configured tags, and requested rationale at the inference boundary; keep task activity separate. Store enriched messages in the session manifest and let a dedicated browser-side conversation renderer consume only canonical events and references.

**Tech Stack:** Python 3.15, FastAPI, Pydantic, SQLite task event store, Ollama async streaming API, vanilla JavaScript, CSS, unittest, Node syntax/unit tests, Playwright browser verification.

**Spec:** `docs/superpowers/specs/2026-11-17-streaming-auditable-chat-design.md`

## Global Constraints

- BORG is the only execution path; UI and HTTP handlers do not implement provider, filesystem, or export behavior.
- Public reasoning always carries provenance and is never presented as verified system activity.
- Non-streaming providers keep a completed-response compatibility path.
- Downloads remain bounded to existing session, artifact, task, or active-project authorization.
- No fake browser-side token streaming and no remote transmission by default.
- Existing direct chat, attachments, artifacts, models, and acceleration profiles remain compatible.

## Review Focus

- A provider disconnects after emitting partial text: keep and mark the incomplete assistant turn; cover in Task 3.
- Duplicate or replayed deltas arrive after reconnect: deduplicate by durable event sequence; cover in Task 2 and Task 5.
- Reasoning tags are malformed or unclosed: preserve labeled raw public output and emit a warning; cover in Task 3.
- A reference targets a path outside the active project or another session: return 403 without revealing the path; cover in Task 4.
- A legacy session manifest or non-streaming provider lacks new fields: migrate defaults and render normally; cover in Task 1 and Task 5.

---

### Task 1: Canonical conversation, reasoning, and reference contracts

**Files:**
- Modify: `web_app/models.py`
- Modify: `web_app/workspace.py`
- Test: `test_workspace.py`
- Test: `test_web_api.py`

**Interfaces:**
- Produces: `ReasoningEntry`, `ReasoningTrace`, `ObjectReference`, `MessageArtifact`, and enriched `ChatMessage` contracts; `WorkspaceService.append_message()` persists them while reading schema-v2 manifests with defaults.

- [ ] Write failing contract and legacy-migration tests asserting stable message IDs, statuses, provenance values, typed references, artifact metadata, and schema-v2 default migration.
- [ ] Run `python -m unittest test_workspace.py test_web_api.py` and verify the new assertions fail because the fields and contracts do not exist.
- [ ] Add the minimal Pydantic contracts and workspace migration needed by the tests; keep old manifests valid.
- [ ] Re-run `python -m unittest test_workspace.py test_web_api.py` and verify PASS.
- [ ] Commit the task changes with `feat(chat): add auditable conversation contracts`.

### Task 2: Durable asynchronous task execution and live event replay

**Files:**
- Modify: `web_app/core/service.py`
- Modify: `web_app/core/api.py`
- Modify: `web_app/core/store.py`
- Test: `test_core_service.py`
- Test: `test_core_api.py`

**Interfaces:**
- Consumes: existing `TaskCommand`, `TaskEventDraft`, and `TaskStore`.
- Produces: `CoreService.start(command, principal) -> TaskRecord`, background execution owned by the service, and task-event WebSocket replay that delivers ordered deltas after the submitted sequence.

- [ ] Write failing tests proving `start()` returns a created/running record before a blocked adapter completes, emitted adapter events become immediately subscribable, replay is sequence-deduplicated, and completion/failure is durable.
- [ ] Run `python -m unittest test_core_service.py test_core_api.py` and verify failures are caused by missing asynchronous execution.
- [ ] Split task creation from execution inside `CoreService`, track service-owned background tasks, and expose a non-blocking task submission route while retaining the existing awaited `submit()` behavior for compatibility.
- [ ] Re-run `python -m unittest test_core_service.py test_core_api.py` and verify PASS.
- [ ] Commit with `feat(core): stream durable task events during execution`.

### Task 3: Ollama streaming and public-reasoning normalization

**Files:**
- Create: `web_app/reasoning.py`
- Modify: `web_app/ollama_service.py`
- Modify: `web_app/core/inference_adapter.py`
- Modify: `cli.py`
- Test: `test_reasoning.py`
- Test: `test_core_inference_adapter.py`
- Test: `test_web_api.py`

**Interfaces:**
- Consumes: Task 1 reasoning contracts and Task 2 durable adapter event path.
- Produces: `ReasoningNormalizer.feed(delta)`, `ReasoningNormalizer.finish()`, `OllamaService.stream_chat(...)`, and adapter events `inference.reasoning.delta`, `inference.content.delta`, `inference.reference`, `inference.warning`, and `inference.completed`.

- [ ] Write failing tests for native reasoning fields, configured `<think>` tags, requested public-rationale fallback, malformed/unclosed tags, plain non-streaming responses, and partial-stream failure.
- [ ] Run `python -m unittest test_reasoning.py test_core_inference_adapter.py test_web_api.py` and verify the expected missing-interface failures.
- [ ] Implement bounded normalization and Ollama streaming, emitting real deltas and a final `ChatResult`; do not split an already-complete response to imitate streaming.
- [ ] Re-run `python -m unittest test_reasoning.py test_core_inference_adapter.py test_web_api.py` and verify PASS.
- [ ] Commit with `feat(inference): normalize streamed public reasoning`.

### Task 4: Conversation history, references, and exports API

**Files:**
- Create: `web_app/conversation.py`
- Modify: `web_app/app.py`
- Modify: `web_app/artifacts.py`
- Test: `test_conversation.py`
- Test: `test_attachments_api.py`
- Test: `test_artifacts.py`
- Test: `test_web_api.py`

**Interfaces:**
- Consumes: Task 1 message/reference contracts and durable task IDs.
- Produces: session conversation retrieval, Markdown/JSON conversation export, per-message export, typed reference resolution, and explicitly requested ZIP export through bounded routes.

- [ ] Write failing tests for history order, response/task linkage, attachment and artifact downloads, missing objects, cross-session access, active-project containment, Markdown/JSON export, and opt-in binary ZIP inclusion.
- [ ] Run `python -m unittest test_conversation.py test_attachments_api.py test_artifacts.py test_web_api.py` and verify the new endpoints fail as absent.
- [ ] Implement `ConversationService` and thin FastAPI routes that call it; reuse attachment/artifact stores and reject path escapes.
- [ ] Re-run the focused tests and verify PASS.
- [ ] Commit with `feat(chat): add bounded conversation references and exports`.

### Task 5: Persistent streaming conversation interface

**Files:**
- Create: `web/conversation_view.js`
- Modify: `web/core_client.js`
- Modify: `web/task_view.js`
- Modify: `web/app.js`
- Modify: `web/index.html`
- Modify: `web/app.css`
- Test: `test_conversation_view.py`
- Test: `test_core_web.py`
- Test: `test_web_static.py`

**Interfaces:**
- Consumes: Task 2 live task records, Task 3 delta events, and Task 4 history/reference/export routes.
- Produces: `JSONCodrConversationView`, a message timeline that incrementally applies events by sequence, restores session history, and renders reasoning, activity, references, files, errors, retry lineage, and export actions.

- [ ] Write failing Node/browser-facing unit tests for delta rendering, replay deduplication, history restoration, legacy messages, partial failure, safe text rendering, reference controls, and file association.
- [ ] Run `python -m unittest test_conversation_view.py test_core_web.py test_web_static.py` and verify failures identify the missing conversation view and markup.
- [ ] Implement the conversation renderer and replace the single-result panel while preserving model selection, composer keyboard behavior, uploads, drag-and-drop, cancellation, retry, and direct fallback.
- [ ] Re-run the focused tests and `node --check web/conversation_view.js && node --check web/app.js && node --check web/core_client.js`; verify PASS.
- [ ] Commit with `feat(web): add persistent streaming conversation`.

### Task 6: Integrated verification and live rollout

**Files:**
- Modify only if verification exposes a tested defect.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: a restarted local service and browser-visible proof using a real installed Ollama model.

- [ ] Run the full project test suite with `python -m unittest discover -v` and record all pass/fail counts.
- [ ] Run `python -m compileall -q web_app cli.py` plus JavaScript syntax checks.
- [ ] Restart only the exact JSON_CODR process bound to port 8772, verify `/api/health`, and preserve unrelated processes.
- [ ] Use Playwright in the in-app browser to submit a multi-part prompt, observe at least one real live delta before completion, open rationale/activity panels, upload and download a file, follow a typed reference, reload to prove history persistence, and export Markdown plus JSON.
- [ ] Capture visible browser evidence and report any provider that used the non-streaming compatibility path.

