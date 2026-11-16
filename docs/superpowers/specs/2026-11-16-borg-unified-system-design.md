# JSON_CODR Unified Runtime Design

## Status and naming

This is the design for the JSON_CODR alpha rewrite, developed under the temporary BORG codename. BORG is not a product name, persisted format, API namespace, or user-facing mode. Permanent code and interfaces use neutral JSON_CODR concepts such as `CoreService`, `AgentRuntime`, `CapabilityRegistry`, `TaskStore`, and `PolicyService`.

## Intent

JSON_CODR becomes one local coding system comparable in interaction flow to Codex and Claude Code: the user opens a project, describes an outcome once, and observes one agent loop inspect, edit, execute, verify, and report. Models, hardware profiles, terminal processes, browser automation, skills, MCP, REA, Ghidra, and other modules are capabilities selected inside that loop rather than separate applications the user coordinates.

The rewrite preserves useful JSON_CODR projects, skills, general settings, permissions, benchmark history, and conversations. Continue- and Aider-specific configuration is not part of the permanent architecture and is removed only after the unified runtime passes capability-parity tests.

## Goals

- Present one project, thread, task, result, and checkpoint model across chat, terminal, files, agents, schedules, and APIs.
- Give every operation one durable task identity, ordered events, live output, cancellation, evidence, artifacts, and recovery state.
- Provide first-class repository understanding, multi-file editing, terminal execution, Git workflows, testing, iterative correction, and rollback without requiring Continue or Aider.
- Support native and brokered model execution honestly across all compatible Ollama models and verified CPU, GPU, and NPU profiles.
- Make skills, MCP servers, imported repositories, archives, REA, Ghidra, browser automation, language intelligence, and future modules discoverable through one capability contract.
- Keep routine routing invisible while making the effective model, runtime, capability, policy, provenance, fallback, and verification inspectable.
- Preserve local-first operation and useful functionality when optional modules or accelerators are unavailable.

## Non-goals

- Renaming the JSON_CODR product to BORG.
- Claiming that every model has native tool calling.
- Reproducing the internal architecture of Codex, Claude Code, Continue, or Aider.
- Making every optional module part of the core process or Python environment.
- Guaranteeing equal reasoning quality across local models.
- Requiring cloud orchestration for ordinary local work.

## Anti-goals

- Separate chat, CLI, agent, installer, Git, or analysis execution paths.
- User workflows that require selecting an internal tool before stating the desired outcome.
- Multiple permission stores, context assemblers, task histories, or definitions of success.
- Framework-owned state that can disagree with JSON_CODR task state.
- Simulated tool output, fabricated completion, or capability claims based only on package presence.
- Automatic fallback that hides which model or executor actually performed the work.

## Approaches considered

### JSON_CODR-owned unified runtime — selected

JSON_CODR owns task state, the agent loop, policy, routing, evidence, and capability contracts. Open-source modules operate behind adapters. This produces the simplest permanent user model, keeps dependencies replaceable, and prevents another framework from becoming a second control plane.

### Incrementally reshape beta — rejected as the target architecture

Moving beta handlers behind services one at a time reduces short-term migration risk but makes it easy to preserve duplicate execution and tool-specific concepts. Beta remains a compatibility source during migration, not the architecture being preserved.

### External agent framework as the runtime — rejected

Microsoft Agent Framework or a similar system could accelerate orchestration but would own concepts that JSON_CODR also needs to own. Such frameworks may be optional worker adapters after the core contracts are stable; they are not the task authority.

## User model

The permanent user-visible concepts are:

- **Project:** an approved local workspace and its source-control identity.
- **Thread:** the continuing conversation, objective, resources, and instructions for a project.
- **Task:** one durable unit of work executed by the runtime.
- **Result:** the task's changes, artifacts, findings, and verification evidence.
- **Checkpoint:** a recoverable project state associated with a task boundary.

The ordinary flow is:

1. Open, create, clone, or drop a project.
2. State the desired outcome in the thread and optionally attach files, folders, images, archives, URLs, or repositories.
3. JSON_CODR gathers context, resolves capabilities, selects a compatible model and verified runtime, and begins one task.
4. A unified activity stream shows meaningful progress, requests authority only when required, and accepts steering or cancellation.
5. JSON_CODR verifies the outcome and presents the response, diff, artifacts, tests, evidence, and checkpoint together.
6. The user continues the same thread, retries, branches, restores, or accepts the result.

The user does not launch Continue, Aider, REA, Ghidra, Playwright, MCP, or a hardware backend as a prerequisite. Those are capability implementations chosen by the runtime. Advanced controls may override routing but do not create a separate workflow.

## Runtime architecture

### CoreService

`CoreService` is the only application boundary for task-producing operations. Chat handlers, terminal controls, scheduled jobs, model actions, MCP endpoints, and import flows decode input, call this service, and render returned state. They do not mutate files, launch processes, run Git, install dependencies, invoke inference, or call analysis tools directly.

### AgentRuntime

`AgentRuntime` performs one observable loop:

1. Interpret the requested outcome and constraints.
2. Gather project, thread, instruction, and resource context.
3. Propose or select the next capability call.
4. Ask `PolicyService` to authorize the concrete action.
5. Execute through the resolved adapter.
6. Record real output, mutations, costs, and evidence.
7. Replan after failure or new user steering.
8. Verify completion against explicit task criteria.
9. Create the result and checkpoint.

The loop supports direct tool-calling models and brokered models. Brokered execution uses deterministic parsers, constrained command schemas, or a compatible effective model, but records the requested model, effective model, and executor separately.

### CapabilityRegistry

Every capability publishes a versioned manifest containing:

- stable capability and implementation identifiers
- supported platforms and isolated runtime requirements
- required permissions and approved-root behavior
- native-model requirements and brokered availability
- applicable file, project, and artifact types
- model and hardware compatibility evidence
- health and functional probes
- input and output schemas
- cancellation, rollback, and cleanup behavior
- provenance, signature, and dependency information
- resource limits and observability fields

Package presence is not readiness. A capability becomes runnable only after its functional probe succeeds for the relevant environment. A model-capability pair becomes verified only after a real operation produces the expected evidence.

### TaskStore and event stream

`TaskStore` is the sole durable source of task state. Commands produce ordered events committed before side effects are acknowledged. It stores tasks, attempts, capability calls, approvals, output references, artifacts, verification, checkpoints, interruption state, and parent-child relationships.

All clients consume the same resumable event stream. Reconnection replays events from a sequence cursor. A server restart marks unresolved execution interrupted until recovery proves whether the underlying process remains attached; it never infers completion from silence.

### PolicyService

Policy evaluates concrete capabilities and resources, not user-interface origins. A permission granted to a project applies consistently whether an action begins in chat, terminal, a schedule, an agent, or an MCP request.

Persistent policy may authorize reads, edits, tests, dependency installation in isolated environments, commits, and current-branch pushes inside approved project roots. Destructive operations, credentials, drivers, services, force pushes, and access outside approved roots require stronger authority or remain blocked. Every decision is recorded with the task.

### ExecutionRouter

Routing is compatibility-first:

1. Filter to implementations whose functional probes, platform requirements, and policy requirements pass.
2. Filter to model and hardware pairs verified for the required capability.
3. Prefer the requested model when it can complete the task truthfully.
4. Otherwise select an explicit brokered path and disclose it.
5. Rank remaining paths using task-specific capability quality, stability history, and measured performance.
6. Retain CPU and the last-known-good route as fallbacks.

Routing changes metadata and executors; it does not create a second task.

## Core capabilities

The first complete runtime includes:

- project discovery, search, reading, file creation, and unified patch editing
- syntax indexing and language-server diagnostics
- interactive terminal sessions and bounded command execution
- Git status, diff, worktree isolation, commits, branches, synchronization, pull requests, and checkpoints
- direct Ollama inference and honest compatibility brokering
- multi-agent delegation with isolated contexts and worktrees
- browser inspection, interaction, screenshots, downloads, and UI verification
- skills, project instructions, persistent memory, context compaction, and resumable goals
- MCP clients, resources, prompts, and tools
- scheduled and headless tasks with structured output
- REA evidence collection and Ghidra binary analysis when applicable
- local, archive, URL, GitHub, skill, MCP, and plugin assimilation
- image, document, source-code, pasted-content, and archive ingestion
- lifecycle hooks implemented as task events and policy-controlled subscribers
- secrets references, resource budgets, telemetry, and signed provenance

## Open-source component policy

Libraries fill capability implementations; they do not define application flow. Initial candidates are Playwright, pywinpty/ConPTY, Tree-sitter, multilspy, the official MCP SDK, APScheduler, GitPython, jsonschema, OpenTelemetry, Sigstore, in-toto, SQLite FTS5, and a rebuildable sqlite-vec index. Microsoft Agent Framework may be evaluated as an optional multi-agent worker behind the runtime contract.

Each dependency must pass license review, platform and Python compatibility checks, an isolated installation test, a functional probe, cancellation and cleanup tests, and an end-to-end capability test. Unsupported packages run in versioned provider environments, normally Python 3.12 or 3.14, rather than changing the Python 3.15 core environment. Imported code never receives project or credential access merely because installation succeeded.

## Isolation and execution environments

The core process owns contracts, policy, task state, and routing. Standard provider processes host modules that cannot safely or compatibly run in the core environment. Risky or untrusted components run in component-specific environments or supported containers.

An environment has an immutable manifest, dependency lock, interpreter identity, capability list, health state, project mounts, network policy, secrets scope, and cleanup strategy. The UI reports the environment only in execution details unless intervention is required.

## Multi-agent execution

The runtime may create child tasks for independent work. Each child has a bounded objective, scoped tools, explicit project view, separate context, and, for editing work, an isolated Git worktree. The parent receives structured results and merges deliberately. Agents never concurrently edit the same worktree without an explicit serialized operation.

Named reusable agent profiles specify instructions, model preferences, capability allowlists, budgets, and verification requirements. They remain JSON_CODR profiles rather than identities imposed by an external framework.

## Memory and context

Context has distinct layers:

- system compatibility and safety instructions
- user preferences
- project instructions and conventions
- thread resources and summaries
- task-local evidence and working state
- indexed project symbols and searchable memory

The runtime records the sources included in each model request. Automatic compaction creates a structured summary linked to the original events rather than deleting history. Vector indexes are disposable derivatives; SQLite records and source files remain authoritative.

## Assimilation

Assimilation is a task, not an installer shortcut. It identifies an input, retrieves it into quarantine, records provenance, detects its type and license, scans its manifest and dependencies, determines applicable capabilities, converts supported formats, installs into an isolated environment, probes real behavior, registers verified capabilities, and produces documentation and rollback state.

The same flow handles a skill, MCP server, repository, plugin, model support package, or analysis extension. Inapplicable capabilities are reported as such rather than marked failed. Duplicate identity and content hashes prevent accidental duplicate installation.

## User interface

The main project view contains:

- project and thread navigation
- one conversation and resource composer
- unified live activity for the current task
- results, changes, artifacts, and verification
- stop, steer, retry, branch, undo, and restore controls

An expandable execution-details view contains the requested and effective model, hardware route, native or brokered status, capability calls, environments, policy decisions, terminal output, resource usage, provenance, fallbacks, and probes.

Settings manages projects, model and hardware preferences, capabilities, skills, MCP, schedules, permissions, environments, credentials, diagnostics, updates, and data migration. These settings influence the same runtime rather than launching separate subsystems.

## Failure behavior

- If an optional adapter fails, the task records the failure and selects a verified fallback when one can preserve the requested outcome.
- If no valid fallback exists, the task stops with actionable evidence; it does not substitute a materially different result silently.
- Project mutations occur in checkpoints or isolated worktrees so failed attempts remain reviewable and recoverable.
- Adapter crashes do not corrupt task state or disable the last-known-good direct Ollama and project workflow.
- Installation failures remain quarantined and do not modify the core environment.
- A model response is never treated as proof that an external action occurred.

## Approved product defaults

- The built-in terminal remains fully interactive, but JSON_CODR records its process, input, output, working directory, and lifecycle against the current task. External shells remain outside JSON_CODR tracking guarantees.
- A foreground task edits the active project after creating a checkpoint. Background and concurrent editing agents use isolated Git worktrees and merge deliberately.
- Reads, searches, indexing, bounded edits, and tests proceed automatically inside an approved project. Network access, dependency installation, commits, pushes, destructive actions, credentials, services, and access outside the project require stored or one-time authority.
- A verified brokered model or executor may be selected automatically while execution remains local and inside the same privacy and cost boundary. Cloud access, payment, new credentials, or materially different behavior requires consent.
- Migration imports useful compatible Continue and Aider history once, then removes their runtime dependencies, configuration, adapters, and product terminology.
- The runtime may delegate automatically within a small configurable local concurrency and resource budget. Delegation remains one visible parent task; crossing configured network, cost, or compute limits requires permission.
- Filesystem and Git watchers record external edits. Conflicting tasks pause and replan rather than overwrite work made by an editor, shell, or external Git process.
- Assimilated components become globally available but activate only for the initiating project unless the user promotes or enables them elsewhere.
- Alpha contracts support authenticated reconnection and multiple observers. Full remote control follows the stable local unified runtime.
- History, redacted logs, evidence, and checkpoints use configurable retention limits. Export and import preserve portable state without secrets; large artifacts and old checkpoints can be pruned without corrupting task history.
- Inspection-only schedules may run under project policy. Scheduled edits, commits, pushes, installation, and external actions require explicit persistent authorization for that schedule.
- Local edits appear immediately behind a pre-task checkpoint without an extra apply step. Commit, push, publish, and destructive operations remain separate policy-controlled actions, and undo restores the checkpoint.

## Migration from beta

Migration reads existing JSON_CODR data without requiring the beta server to run. It preserves projects, installed JSON_CODR skills, general settings, compatible permissions, benchmark history, imported resources, and useful conversations. It translates supported terminal and agent history into thread/task events when provenance is sufficient.

Continue- and Aider-specific launch settings, duplicated permission records, and tool-specific session state are not permanent concepts. They remain readable during the parity period and are archived or removed after equivalent JSON_CODR capabilities pass migration and live acceptance tests.

The alpha implementation uses a strangler migration internally: a beta behavior is wrapped behind a permanent capability contract, parity-tested through `CoreService`, and then its direct route is removed. No beta handler becomes a permanent alternate path.

## Compatibility and acceptance gates

The unified runtime is ready only when tests prove:

- chat, terminal, schedules, API, and agent actions create tasks through `CoreService`
- all clients observe the same ordered events and task identity
- direct filesystem mutation, subprocess, Git, installer, inference, REA, and Ghidra calls exist only in registered adapters
- a normal coding request can inspect, edit, test, correct, checkpoint, and report without choosing an internal executor
- all installed models are classified truthfully as native, brokered, or unsupported for each capability
- CPU and last-known-good Ollama operation survive optional adapter and accelerator failure
- concurrent editing agents use isolated worktrees and merge with evidence
- restart, reconnect, cancellation, steering, and rollback preserve truthful state
- project authorization cannot escape approved roots through any surface
- an assimilated component cannot execute until provenance, policy, environment, and functional probes pass
- existing beta data migrates without loss of supported user data
- the web interface remains responsive and exposes advanced detail without adding steps to the ordinary flow

## Documentation outcome

Shipped documentation uses JSON_CODR terminology and explains user tasks, not internal modules. Architecture documentation may note that the alpha rewrite used the BORG codename, but APIs, schemas, saved files, logs, and UI do not depend on that name.
