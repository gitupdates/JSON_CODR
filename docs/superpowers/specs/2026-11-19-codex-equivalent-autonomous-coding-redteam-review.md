# Codex-Equivalent Autonomous Coding Redteam Review

Date: 2026-11-19

Scope: `2026-11-19-codex-equivalent-autonomous-coding-design.md` and the current Workspace, `AgentRuntime`, policy, Git broker, local Ollama, command, infrastructure, and deployment boundaries.

## Review standard

Agreement requires no unresolved critical or high-severity design finding. Medium and low risks must have an owner, an explicit control, and an acceptance test. This review does not certify an implementation that has not yet been written; the same gates must be rerun against code and real local-model behavior before release.

## Threat actors and untrusted inputs

- A local model emitting malformed, misleading, over-broad, or adversarial actions.
- Malicious repository instructions, source files, dependencies, manifests, tests, and generated profiles.
- Compromised tool, adapter, MCP server, package, container image, or deployment endpoint.
- Browser, connector, command, compiler, test, log, and remote API output containing prompt injection or terminal escapes.
- A concurrent local process changing the project, branch, credentials, environment, or remote state.
- An authorized user approving one payload while a different payload executes.
- Accidental operator selection of the wrong project, account, subscription, cluster, namespace, or production environment.

## Findings and disposition

### RT-01 — Automatic Git grants bypass approval — Critical — Resolved in design

Current code grants commit/sync/push authority inside execution. The design removes automatic grants, evaluates every call independently, and requires one-use canonical approval for sensitive Git effects.

### RT-02 — Implicit fetch violates local-only execution — Critical — Resolved in design

Current Git broker fetches whenever an upstream exists. The design prohibits implicit network operations and models fetch/sync/push as separate approved calls.

### RT-03 — Single-shot Workspace cannot safely inspect then edit — High — Resolved in design

The current endpoint asks for actions before returning read results to the model. The design routes Workspace through iterative `AgentRuntime` planning with persisted child results and fresh context.

### RT-04 — Failed verification can leave repository mutations — High — Resolved in design

The current broker applies directly and does not roll back on later failure. The design requires isolated worktrees or byte-exact checkpoints, writer locking, fingerprint checks, and reported recovery state.

### RT-05 — Approval confusion and replay — Critical — Resolved in design

Broad persistent grants and aggregate policy can authorize different actions. The design binds one-use approval to principal, task/step revision, project, canonical call, fingerprint, target, expiry, and atomic consumption.

### RT-06 — Prompt injection through project/tool content — High — Resolved in design

Repository instructions and outputs enter planner context. The amended design assigns untrusted provenance and prohibits this content from changing policy, schemas, scope, credentials, targets, or approval state.

### RT-07 — Approved commands retain host-level danger — Critical — Resolved in design

Tests, builds, and project scripts can be malicious. The amended design requires constrained execution, sanitized environment, budgets, cancellation, explicit network authority, sandbox-degradation disclosure, and default denial for production operations without adequate isolation.

### RT-08 — Credential and secret exfiltration — Critical — Resolved in design

The amended design excludes secret sources from default context, uses opaque adapter-resolved references, propagates sensitivity labels, requires data-boundary approval for external routes, and redacts before persistence/display.

### RT-09 — Infrastructure target and rollback ambiguity — Critical — Resolved in design

The amended design binds account/environment/region/cluster/namespace/target, separates preview from apply, states rollback class before approval, and treats unavailable rollback as a blocking high-risk condition.

### RT-10 — Model or adapter drift invalidates verification — High — Resolved in design

Broker conformance is bound to exact model digest, runtime, prompt-contract, and adapter versions. Any change requires re-verification.

### RT-11 — Concurrent task and TOCTOU races — High — Resolved in design

The amended design adds per-project writer locks, optimistic fingerprints, atomic approval consumption, and remote-state validation immediately before external effects.

### RT-12 — Output spoofing and terminal-control injection — High — Resolved in design

Canonical approval fields are rendered separately from model prose. Tool output is untrusted, escape-safe, inert, bounded, and unable to generate approval authority.

### RT-13 — Resource exhaustion and infinite repair loops — High — Resolved in design

The amended design requires limits for model turns, retries, context, output, runtime, process count, and provider failures, ending in an explicit blocked state.

### RT-14 — Capability registry becomes a privilege-escalation surface — High — Resolved in design

Capabilities are versioned, probed, typed, policy-visible, and adapter-backed. Model-created or changed project profiles cannot execute until deterministic rediscovery and user review.

### RT-15 — Audit records leak secrets or cannot prove sequence — Medium — Resolved in design

The amended design redacts before persistence and uses the existing hash-linked task event chain with bounded retention and high-risk identity/digest evidence.

## Required implementation gates

1. Tests must first reproduce every current critical path: automatic Git grant, implicit fetch, broad broker grant, single-shot context failure, and mutation persistence after verification failure.
2. Each control is implemented by the narrowest responsible component and verified red-green before later features rely on it.
3. Security tests include malicious repository instructions and command output, not only cooperative fixtures.
4. Real-model conformance runs in a disposable repository with no credentials and no network authority.
5. Infrastructure/deployment conformance uses fake or sandbox targets until an operator separately authorizes a named non-production environment.
6. Full-suite regressions and known environment failures are reported separately; no security failure is waived as environment-sensitive.
7. Release remains blocked until a second code-level Redteam review finds no unresolved critical or high issue.

## Design-level decision

**Agreement: PASS WITH IMPLEMENTATION GATES.** All critical and high design findings have explicit controls and acceptance requirements. This is agreement with the amended design, not certification of future code. Implementation and release require the gates above and a final adversarial verification of the actual diff and real-model behavior.
