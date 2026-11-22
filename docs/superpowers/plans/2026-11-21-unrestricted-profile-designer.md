# Unrestricted Profile Designer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unrestricted administrator visual composition and account capability profiles without allowing design changes to interrupt JSON_CODR's running core application.

**Architecture:** Extend the existing structured Designer with separate design, capability, assignment, and executable-extension contracts. Drafts render in isolation; only validated immutable snapshots publish through an atomic pointer swap, with legacy state and last-known-good recovery fallbacks.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLite/file-backed atomic stores, vanilla JavaScript, CSS, existing JSON_CODR Designer contracts and tests.

**Spec:** `docs/superpowers/specs/2026-11-21-unrestricted-profile-designer-design.md`

## Global Constraints

- Owner recovery authority and the fixed recovery shell cannot be removed by a profile.
- Administrator is unrestricted by default, but executable-code permissions remain separately named and auditable.
- The server enforces every mutation and publication; hidden UI controls are not authorization.
- Drafts and previews never mutate the active runtime snapshot.
- Publication is atomic and retains the last known-good snapshot on every failure.
- Imports never activate scripts, assignments, credentials, grants, or permissions.
- Existing appearance presets and workspace layouts retain a tested fallback throughout migration.

## Review Focus

- Deleting or replacing navigation must preserve accessible routes to core functions; Task 3 tests the protected capability graph.
- A corrupt or incompatible component migration must leave the active snapshot unchanged; Tasks 2 and 4 test atomic rejection and fallback.
- Explicit denial must override role and profile grants at every scope; Task 1 tests policy precedence.
- Imported profiles containing scripts or permission-shaped fields must remain quarantined and inert; Task 5 tests import normalization.
- Concurrent administrators must receive a conflict instead of silently overwriting a published revision; Task 2 tests expected-revision writes.

---

### Task 1: Capability Profiles and Assignments

**Files:**
- Create: `web_app/designer/access.py`
- Modify: `web_app/designer/contracts.py`
- Modify: `web_app/models.py`
- Modify: `web_app/app.py`
- Test: `test_designer_access.py`

**Interfaces:**
- Consumes: authenticated account identity and existing authorization context.
- Produces: `CapabilityProfile`, `ProfileAssignment`, `DesignPolicyContext`, and `resolve_design_capability(context, resource, action) -> PolicyDecision`.

- [ ] **Step 1: Write failing precedence and default-profile tests**

Add `test_explicit_resource_deny_overrides_role_and_profile_grants`, `test_owner_retains_recovery_authority`, `test_administrator_defaults_include_unrestricted_design_actions`, and `test_script_authority_is_distinct_from_visual_design_authority`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m unittest test_designer_access.py -v`
Expected: import or contract failures for the missing access module.

- [ ] **Step 3: Implement the contracts and deny-first resolver**

Use stable action identifiers from the spec and reject unknown resources/actions by default. Keep assignments separate from portable design data.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `python -m unittest test_designer_access.py test_designer_contracts.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/designer/access.py web_app/designer/contracts.py web_app/models.py web_app/app.py test_designer_access.py
git commit -m "feat(designer): add capability profiles"
```

### Task 2: Immutable Published Snapshots

**Files:**
- Create: `web_app/designer/publication.py`
- Modify: `web_app/designer/store.py`
- Modify: `web_app/designer/contracts.py`
- Test: `test_designer_publication.py`
- Test: `test_designer_store.py`

**Interfaces:**
- Consumes: `DesignDocument`, `DesignPolicyContext`, current revision digest.
- Produces: `PublishedSnapshot`, `ValidationReport`, `PublicationService.publish(project_id, draft, expected_revision, context) -> PublishedSnapshot`, and `PublicationService.current(project_id) -> PublishedSnapshot`.

- [ ] **Step 1: Write failing atomicity, conflict, and fallback tests**

Add `test_invalid_draft_cannot_change_current_snapshot`, `test_stale_expected_revision_returns_conflict`, `test_materialization_failure_retains_last_known_good_snapshot`, and `test_reader_observes_whole_old_or_whole_new_snapshot`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m unittest test_designer_publication.py -v`
Expected: missing publication service.

- [ ] **Step 3: Implement materialize-then-swap publication**

Write immutable revision and validation report first, fsync/close it, then atomically replace the published pointer. Never modify the current pointer on validation or materialization failure.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `python -m unittest test_designer_publication.py test_designer_store.py test_designer_contracts.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/designer/publication.py web_app/designer/store.py web_app/designer/contracts.py test_designer_publication.py test_designer_store.py
git commit -m "feat(designer): publish immutable snapshots"
```

### Task 3: Core-Function Continuity Validator

**Files:**
- Create: `web_app/designer/continuity.py`
- Modify: `web_app/designer/json_codr_manifest.py`
- Modify: `web_app/designer/components.py`
- Test: `test_designer_continuity.py`

**Interfaces:**
- Consumes: candidate `DesignDocument`, component registry, application manifest.
- Produces: `CoreCapability`, `ContinuityViolation`, and `validate_runtime_continuity(document, manifest, registry) -> tuple[ContinuityViolation, ...]`.

- [ ] **Step 1: Write failing required-route and migration tests**

Add `test_core_function_may_move_or_change_visuals_but_remains_reachable`, `test_deleting_last_route_to_core_function_blocks_publication`, `test_unknown_component_requires_fallback_and_migration`, and `test_recovery_shell_is_not_an_editable_node`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m unittest test_designer_continuity.py -v`
Expected: missing continuity module.

- [ ] **Step 3: Implement capability-graph validation**

Validate semantic routes rather than fixed positions. Require workspace navigation, identity/authentication, task execution, settings, recovery, and safe mode; include component version, migration, and fallback checks.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `python -m unittest test_designer_continuity.py test_designer_components.py test_designer_contracts.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/designer/continuity.py web_app/designer/json_codr_manifest.py web_app/designer/components.py test_designer_continuity.py
git commit -m "feat(designer): protect runtime continuity"
```

### Task 4: Runtime Snapshot Loader and Legacy Migration

**Files:**
- Create: `web_app/designer/migration.py`
- Create: `web/designer_runtime.js`
- Modify: `web/ui_bootstrap.js`
- Modify: `web/ui_customization.js`
- Modify: `web/workspace_layout.js`
- Modify: `web/index.html`
- Test: `test_designer_migration.py`
- Test: `test_ui_customization.py`
- Test: `test_workspace_layout.py`

**Interfaces:**
- Consumes: published snapshots, `json_codr_ui_v1`, and `json_codr_workspace_layout_v1`.
- Produces: `migrate_legacy_profile(...) -> DesignDocument`, `loadRuntimeSnapshot(options) -> RuntimeSnapshot`, and a reversible migration marker.

- [ ] **Step 1: Write failing parity and failure-recovery tests**

Add `test_legacy_appearance_and_layout_import_without_mutating_sources`, `test_new_snapshot_failure_falls_back_to_legacy_controllers`, `test_migration_is_idempotent`, and `test_existing_sessions_keep_last_known_good_snapshot_during_publish`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m unittest test_designer_migration.py test_ui_customization.py test_workspace_layout.py -v`
Expected: new migration/runtime tests fail while existing tests remain green.

- [ ] **Step 3: Implement read-new/fallback-old runtime loading**

Do not delete legacy values. Retire their write path only after a successful marker and parity validation; retain a safe-mode bypass.

- [ ] **Step 4: Run focused tests and syntax checks**

Run: `python -m unittest test_designer_migration.py test_ui_customization.py test_workspace_layout.py test_web_static.py -v; node --check web/designer_runtime.js; node --check web/ui_bootstrap.js`
Expected: all tests and syntax checks pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/designer/migration.py web/designer_runtime.js web/ui_bootstrap.js web/ui_customization.js web/workspace_layout.js web/index.html test_designer_migration.py test_ui_customization.py test_workspace_layout.py
git commit -m "feat(designer): migrate profiles without downtime"
```

### Task 5: Quarantined Executable Extensions and Portable Profiles

**Files:**
- Create: `web_app/designer/extensions.py`
- Create: `web_app/designer/profiles.py`
- Modify: `web_app/designer/assets.py`
- Modify: `web_app/designer/references.py`
- Modify: `web_app/app.py`
- Test: `test_designer_extensions.py`
- Test: `test_designer_profiles.py`

**Interfaces:**
- Consumes: access decisions, assets, references, design documents.
- Produces: `ExecutableExtension`, `ExtensionApproval`, `DesignProfileArchive`, `ProfileService.import_archive(...)`, and `ExtensionService.activate(...)`.

- [ ] **Step 1: Write failing quarantine, portability, and limit tests**

Add `test_import_strips_assignments_grants_credentials_and_sessions`, `test_imported_script_is_inert_until_separate_approval`, `test_extension_capability_token_is_scoped_and_revocable`, and `test_invalid_digest_or_component_version_blocks_activation`.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m unittest test_designer_extensions.py test_designer_profiles.py -v`
Expected: missing extension/profile services.

- [ ] **Step 3: Implement quarantine and checked export/import**

Keep extension authority outside the profile archive. Record provenance, source digest, requested host APIs, limits, review state, and destination compatibility.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `python -m unittest test_designer_extensions.py test_designer_profiles.py test_designer_assets.py test_designer_references.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/designer/extensions.py web_app/designer/profiles.py web_app/designer/assets.py web_app/designer/references.py web_app/app.py test_designer_extensions.py test_designer_profiles.py
git commit -m "feat(designer): quarantine portable extensions"
```

### Task 6: Visual Canvas and Profile Administration

**Files:**
- Create: `web/designer_app.js`
- Create: `web/designer_renderer.js`
- Create: `web/designer.css`
- Modify: `web/designer_commands.js`
- Modify: `web/designer_model.js`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Test: `test_designer_web.py`
- Test: `test_designer_commands.py`

**Interfaces:**
- Consumes: publication, access, continuity, profiles, assets, and extension APIs.
- Produces: canvas/layers/inspector/profile/access/history UI, drag/drop, resize, image paste, responsive preview, undo/redo, draft validation, and explicit publish controls.

- [ ] **Step 1: Extend existing command tests before UI changes**

Add command cases for move, resize, replace, group, delete, paste asset, token edit, breakpoint override, undo/redo, stale revision, permission denial, and continuity rejection.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m unittest test_designer_web.py test_designer_commands.py -v`
Expected: new command and shell cases fail.

- [ ] **Step 3: Implement the editor against structured commands**

Keep the client declarative: it emits commands and displays server validation. Never write directly into the active application DOM or published snapshot.

- [ ] **Step 4: Verify focused tests and JavaScript syntax**

Run: `python -m unittest test_designer_web.py test_designer_commands.py test_designer_contracts.py -v; node --check web/designer_app.js; node --check web/designer_renderer.js; node --check web/designer_commands.js; node --check web/designer_model.js`
Expected: all tests and syntax checks pass.

- [ ] **Step 5: Perform real-browser visual verification**

Verify drag/drop, resizing, image paste, desktop/tablet/mobile preview, permission changes, failed-publication continuity, safe mode, keyboard operation, and no console errors. Capture before/after evidence.

- [ ] **Step 6: Commit**

```powershell
git add web/designer* web/index.html web/app.js test_designer_web.py test_designer_commands.py
git commit -m "feat(web): add unrestricted profile designer"
```

### Task 7: Recovery Drill and Integrated Verification

**Files:**
- Modify: `README.md`
- Modify: user guide section that owns Designer usage.
- Test: focused Designer, settings, workspace, recovery, and static suites.

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: verified migration, rollback, safe-mode, and operator guidance.

- [ ] **Step 1: Run the focused automated suite**

Run: `python -m unittest test_designer_access.py test_designer_publication.py test_designer_continuity.py test_designer_migration.py test_designer_extensions.py test_designer_profiles.py test_designer_web.py test_designer_commands.py test_designer_contracts.py test_designer_store.py test_designer_components.py test_designer_assets.py test_designer_references.py test_ui_customization.py test_workspace_layout.py test_web_static.py -v`
Expected: zero failures.

- [ ] **Step 2: Run JavaScript syntax and diff checks**

Run: `node --check web/designer_app.js; node --check web/designer_renderer.js; node --check web/designer_commands.js; node --check web/designer_model.js; node --check web/designer_runtime.js; git diff --check`
Expected: all commands exit zero.

- [ ] **Step 3: Perform the recovery drill**

Publish a valid profile, attempt invalid navigation deletion, attempt an incompatible component, activate then revoke an approved extension, corrupt the candidate pointer, and confirm every failure retains or restores the last known-good snapshot. Disable all extensions and verify the fixed recovery shell and legacy fallback.

- [ ] **Step 4: Update concise user guidance**

Document how to create, preview, assign, publish, export/import, roll back, disable extensions, and enter safe mode. Do not duplicate implementation internals.

- [ ] **Step 5: Commit**

```powershell
git add README.md docs/user
git commit -m "docs: explain profile designer recovery"
```
