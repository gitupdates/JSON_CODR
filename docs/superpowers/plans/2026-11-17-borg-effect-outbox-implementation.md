# BORG Effect Outbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first BORG production slice: atomic task-event and effect-intent persistence with durable, reconciliation-safe effect states.

**Architecture:** Extend the existing contracts and `TaskStore`; do not add a second orchestrator or cut over adapters yet. A single SQLite transaction appends an event and reserves an idempotent effect, while guarded transitions enforce the approved state machine and unresolved effects block terminal completion.

**Tech Stack:** Python 3.15, Pydantic v2, SQLite, unittest

**Spec:** `docs/superpowers/specs/2026-11-17-borg-unified-execution-design.md`

## Global Constraints

- No new server, framework, hosted dependency, or paid service.
- Preserve existing chat, CLI, agent, Ollama, REA, Ghidra, and acceleration behavior.
- Do not claim exactly-once external effects.
- Route-before-effect and no legacy fallback after effect reservation.
- JSON payloads remain bounded to 262144 bytes.

## Review Focus

- Duplicate reservation for one task/effect returns the original effect and never duplicates work.
- Transaction failure leaves neither the task event nor effect row committed.
- Invalid or stale state transitions fail without mutating the durable row.
- Unknown effects block task completion and automated retry until reconciliation.
- Restart preserves pending and unknown effects with their attempt and lease metadata.

---

### Task 1: Effect contracts

**Files:**
- Modify: `web_app/core/contracts.py`
- Test: `test_core_store.py`

**Interfaces:**
- Produces: `EffectState`, `EffectIntentDraft`, and `EffectIntent`.

- [ ] Write contract tests for frozen bounded payloads and durable-only identity/state fields.
- [ ] Run the focused tests and verify they fail because the contracts do not exist.
- [ ] Add the minimal Pydantic contracts and approved state values.
- [ ] Run the focused tests and verify they pass.

### Task 2: Atomic reservation and replay

**Files:**
- Modify: `web_app/core/store.py`
- Test: `test_core_store.py`

**Interfaces:**
- Consumes: `EffectIntentDraft`.
- Produces: `TaskStore.append_with_effect(task_id, event, effect, expected_version=None) -> EffectReservation`, `TaskStore.effect(task_id, effect_id) -> EffectIntent`, and `TaskStore.effects(task_id, states=None) -> tuple[EffectIntent, ...]`.

- [ ] Write failing tests for atomic reservation, idempotent replay, conflicting replay, rollback, and restart persistence.
- [ ] Add the `effects` table and transaction-scoped reservation.
- [ ] Run the focused store tests and verify they pass.

### Task 3: Guarded transitions and completion barrier

**Files:**
- Modify: `web_app/core/store.py`
- Test: `test_core_store.py`

**Interfaces:**
- Produces: `TaskStore.transition_effect(...) -> EffectIntent`, `TaskStore.reconcile_effect(...) -> EffectIntent`, and terminal-event completion guards.

- [ ] Write failing tests for valid transitions, stale transitions, invalid transitions, unknown reconciliation, and completion blocking.
- [ ] Implement the minimal guarded transition and reconciliation behavior.
- [ ] Run focused and core tests.

### Task 4: Runtime and live regression verification

**Files:**
- No production file changes.

**Interfaces:**
- Validates the slice without routing a production adapter through it.

- [ ] Restart the exact local service process and verify `/api/health` reports ready with Ollama available.
- [ ] Reload the in-app browser, exercise chat and CLI surfaces, and inspect browser errors.
- [ ] Review the scoped diff and commit only this slice with `feat(core): add atomic durable effect outbox`.
