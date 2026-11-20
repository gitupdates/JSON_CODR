# BORG Unified Execution Design

## Goal

Make JSON_CODR behave as one coding agent by routing every migrated side effect through one durable service path without replacing the existing adapters, streaming transports, or local runtimes.

## Authority boundary

`BorgService` is a thin facade over the existing task contracts and store. `TaskCommand`, `TaskEventDraft`, and `TaskEvent` remain the command and event authority. Chat, CLI, agents, MCP, REA, Ghidra, Git, installers, terminals, and browser automation may adapt requests, but they do not independently persist or execute migrated side effects.

The task command receipt, task events, authoritative task projection, and effect intention commit in one SQLite transaction. External effects are dispatched at least once. The system never claims exactly-once execution.

## Durable effects

Each effect has a stable identifier, task owner, capability and operation, versioned payload, authenticated principal, project identity and root, effect class, approval and retry classifications, reconciler identifier, correlation and causation identifiers, bounded payload, durable state, lease information, attempt count, and timestamps.

The state machine is:

`pending -> leased -> running -> succeeded | failed | cancel_requested | unknown_requires_reconciliation`

`cancel_requested -> cancelled | unknown_requires_reconciliation`

An effect in `unknown_requires_reconciliation` blocks task completion and all automatic retries. A capability-specific reconciler must classify it as `succeeded`, `not_applied`, or `still_unknown`; unreconcilable effects require a user decision.

## Streaming and interactive sessions

High-volume tokens, terminal bytes, and browser events do not enter the task event log. BORG owns session creation, authorization, attachment, resize, interrupt, cancellation, and close. Existing WebSocket and session transports remain the data plane. Inference initially uses transient streaming, coalesced durable progress, one raw response artifact, and one completion event.

## Migration

Migration is a strict strangler. Routing occurs before any side effect. After an effect intent exists, legacy execution is forbidden. Legacy paths remain only for explicitly unmigrated capabilities and are removed after parity, restart, cancellation, approval, large-output, and live-UI gates pass.

Slices ship in this order:

1. Atomic effect outbox, leases, unknown-state reconciliation, and crash tests.
2. Inference and event-derived conversation projections.
3. Verified bounded worktree editing.
4. Individually classified MCP, REA, and Ghidra operations.
5. Git and installation mutations with reconcilers.
6. Terminal and browser control planes.
7. Durable schedules and delegation.

## Compatibility guarantees

Existing Ollama chat, CLI, skill, benchmark, and agent paths remain operational during migration. Native model tool support is reported separately from compatibility-layer execution. No adapter may manufacture evidence, capability, or success. Read projections are cursor-based, idempotent, and rebuildable; projection lag cannot fail an authoritative task.
