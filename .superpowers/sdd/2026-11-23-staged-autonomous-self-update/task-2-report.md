# Task 2 report: canonical capability operations

Commit: `36ed8d62b80f341229586ad2c79835ada49ad5f3` (`fix(policy): bind capabilities to canonical operations`)

## Delivered

- Added a server-owned immutable `CapabilityDefinition` and `CapabilityRegistry` in `web_app/core/capability_registry.py`.
- Added canonical mappings for native reads/writes/edits/shell, Git, project, checkpoint, terminal, component, activation, and rollback capabilities. Registered adapters now fail startup if no declaration exists.
- `CoreService.start` normalizes each call before policy evaluation or adapter execution. A supplied compatibility operation must exactly match the server declaration, so `operation="read"` cannot relabel `native.shell`, writes, edits, Git execution, activation, or rollback.
- Policy grants now bind the canonical operation plus a canonical digest of target path and arguments, expire after 30 days by default, and reject expired or changed calls. Existing unconstrained rows are renamed into disabled `policy_legacy_grants` records during migration.
- Application startup supplies declarations for MCP adapters, and the legacy Git bridge uses canonical `git` rather than deriving a caller-visible operation from action kinds.
- Updated supervised approval fixtures to use real canonical sensitive capabilities; the legacy Git bridge remains explicit-approval-only and does not auto-consume a grant.

## Files changed

- `web_app/core/capability_registry.py` (new)
- `web_app/core/policy.py`
- `web_app/core/service.py`
- `web_app/app.py`
- `test_core_policy.py` (new)
- `test_core_service.py`
- `test_core_native_primitives.py`
- `test_core_approval.py`
- `test_core_api.py`

## Tests and verification

- RED: `C:\Python315\python.exe -m unittest test_core_policy.py test_core_service.py test_core_native_primitives.py` failed as intended before implementation: missing registry, spoofed calls reached adapters, unconstrained grants matched, and grants lacked expiry support.
- GREEN: `C:\Python315\python.exe -m unittest test_core_api.py test_core_policy.py test_core_service.py test_core_native_primitives.py test_core_approval.py` — 41 tests passed.
- `C:\Python315\python.exe -m py_compile web_app\app.py web_app\core\capability_registry.py web_app\core\policy.py web_app\core\service.py` passed.
- `git diff --check` passed before staging.

## Security invariants

- Capability ID, not caller-supplied operation text, fixes the operation and risk/autonomy classification.
- A mismatched compatibility operation fails before adapter selection or execution.
- Unknown adapters cannot be registered without a server-owned definition.
- Persistent approval is scoped to principal, project, capability, canonical operation, schedule/project scope, target path, and arguments; it expires.
- Legacy unconstrained grants remain preserved for audit but cannot authorize execution.
- Adapter events and exact-approval/grant paths consume the normalized canonical call.

## Residual risks

- Dynamic MCP definitions are server-created at startup but share a single canonical `mcp` operation; any future multiple-risk MCP modes need separate capability IDs or an explicit server-owned sub-operation registry.
- Existing test fixtures intentionally log rejected adapter and spoof attempts; the test suite passes, but those expected log traces remain visible.
- The historical policy-grant migration assumes `policy_legacy_grants` is not already present from an interrupted or manually modified migration; operational migration recovery is outside this task's scope.

## Fix round: red-team hardening

Commit: `124f7284f574ace0a92ec39802cd0b58e3fbc3f9` (`fix(policy): harden capability grant boundaries`)

### RED evidence

- `test_core_policy.py` exposed persistent grant replay when a call changed its root, execution mode, privacy/cost boundaries, or credential references; caller-supplied `schedule_id` selected a schedule grant; an existing legacy table collided with migration; and a sensitive capability could be marked autonomous.
- `test_core_service.py` showed invalid capability calls were stored before normalization and that a server project registration did not constrain the persisted root.
- `test_agent_runtime.py`, `test_agent_services.py`, and `test_core_adapter_fallback.py` failed against the previous registry because `project.patch="replace"`, `test.run`, and MCP discovery/invocation contracts no longer matched its definitions.

### GREEN evidence

- `C:\Python315\python.exe -m unittest test_core_service.py test_core_policy.py test_core_adapter_fallback.py test_agent_runtime.py test_agent_services.py test_core_native_primitives.py test_mcp_stdio_backend.py` — 76 passed.
- Expanded focused regression run covering policy/service, agent runtime/services, MCP fallback/registration, automation, approvals, project runtime, native primitives, and representative web routes — 93 passed.
- `C:\Python315\python.exe -m py_compile web_app\app.py web_app\core\capability_registry.py web_app\core\policy.py web_app\core\service.py web_app\core\scheduler.py web_app\core\delegation.py web_app\core\mcp_stdio_backend.py` and `git diff --check` passed.

### Files

- Policy and persistence hardening: `web_app/core/policy.py`, `web_app/core/service.py`, `web_app/core/scheduler.py`, `web_app/core/capability_registry.py`.
- Compatibility inventory: `web_app/app.py`, `web_app/core/mcp_stdio_backend.py`, `web_app/core/delegation.py` and the affected supervised/MCP tests.

### Residual risks

- Schedule identity is accepted only through `CoreService`'s server-only scheduler context; callers submitting a `schedule_id` without that context are rejected. Code that bypasses `CoreService` and writes directly to `TaskStore` remains outside this service boundary.
- The full `test_web_api.py` suite still has pre-existing Task 1 authentication-fixture failures (401/403 expectation drift); the focused web chat and MCP catalog cases affected by this fix passed.

## Fix round 2: immutable capability target binding

### Delivered

- `AgentRuntime` now asks `CoreService` to normalize and bind a planner call before atomically reserving its child task, so an unknown or aliased planner call cannot be persisted first.
- `CoreService` fails closed without a `ProjectRegistry`; every persisted executable call has a registered, canonical project root.
- `ProjectRegistry` records trusted parent-project lineage. Editing delegation registers the newly created worktree as a child project and executes the child under that distinct project ID.
- Persistent-grant digests bind the resolved effective target path, so retargeting an in-project symlink invalidates a previous approval.
- Git and terminal app bindings register and use the effective requested/session root and corresponding project ID instead of forcing the default project root.

### Tests and verification

- `C:\Python315\python.exe -m unittest test_agent_runtime.py test_core_automation.py test_core_policy.py test_core_service.py test_core_project_registry.py` — 56 passed.
- `C:\Python315\python.exe -m unittest test_core_api.py test_core_approval.py test_agent_services.py test_core_adapter_fallback.py test_core_native_primitives.py test_mcp_stdio_backend.py` — 50 passed.
- `C:\Python315\python.exe -m py_compile web_app\app.py web_app\core\agent_runtime.py web_app\core\delegation.py web_app\core\policy.py web_app\core\project_registry.py web_app\core\service.py` — passed.
- `git diff --check` — passed.

### Self-review

- Confirmed normalization occurs before planner-child persistence and still occurs at execution time.
- Confirmed no-registry execution is rejected before task creation, normal root aliases are persisted canonically, and delegated worktrees have distinct registered lineage.
- Confirmed the digest uses the resolved target rather than user-supplied spelling and that Git/terminal calls carry the registered target project ID.

### Files

- Production: `web_app/core/agent_runtime.py`, `web_app/core/delegation.py`, `web_app/core/policy.py`, `web_app/core/project_registry.py`, `web_app/core/service.py`, `web_app/app.py`.
- Tests: `test_agent_runtime.py`, `test_core_automation.py`, `test_core_policy.py`, `test_core_service.py`, `test_core_api.py`, `test_core_approval.py`.

### Concerns

- `ProjectRegistry` registration remains the trust boundary for non-default Git and terminal roots; endpoint authorization determines which local roots may be registered.
- The full unrelated web API suite was not rerun; earlier Task 1 authentication-fixture expectation drift remains outside this scoped change.
