# Account-Aware UI Designer and Source-Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure localhost accounts and capability policy, account-scoped GitHub/Git, permission-aware UI overlays and Designer controls, and a compact editable Source Control workspace.

**Architecture:** A transactional SQLite security plane supplies `AuthContext`, policy, audit, recovery, and ownership to existing FastAPI services. The existing structured scene model remains the UI source of truth; immutable overlays compose base, shared, group, and personal layers. Source Control becomes the first complete account-aware editable application page, while GitHub CLI and Git run through an account-bound environment.

**Tech Stack:** Python 3.14, FastAPI, Pydantic 2, SQLite, Argon2id, vanilla JavaScript/CSS, GitHub CLI, Git, unittest, Node syntax checks.

**Spec:** `docs/superpowers/specs/2026-11-21-account-aware-ui-designer-source-control-design.md`

## Global Constraints

- Bind production startup only to IPv4/IPv6 loopback and reject unapproved Host and Origin values.
- Use stable UUIDs for accounts and storage; usernames never identify storage paths.
- Store no default password, raw session token, CSRF secret, GitHub token, password, cookie, or device code in logs or browser storage.
- Explicit denial overrides grants; protected invariants outrank all grants; unknown capabilities and resources default-deny.
- New accounts receive Preferences and User; Designer, Admin, and Developer are explicit grants.
- Every API, WebSocket message, background effect, subprocess, export, and Designer command declares a capability/resource rule.
- Existing machine-global GitHub credentials are never copied into an account.
- Account switching ends the current session, clears account-bound browser state, and requires login to the next account.
- Overlay order is base → shared → ordered group → personal; invalid layers quarantine instead of partially applying.
- Safe mode bypasses overlays, never authentication or authorization.
- Preserve the existing GitHub safety contract: exact branch/checkout match, clean tree, serialized mutation, exact-SHA revalidation, confirmation, and fast-forward only.
- Use `apply_patch` for source edits, preserve unrelated changes, and commit each task independently.

## Review Focus

- A revoked account has an active WebSocket and Git operation: the policy epoch must close/cancel or reauthorize both before effect commit (Task 3 and Task 8).
- Two accounts reference the same checkout through different path spellings or reparse points: canonical ownership and serialized mutation must prevent cross-account bypass (Task 5 and Task 8).
- Migration crashes after backup but before ownership is complete: restart must resume or restore without mixed global/account state (Task 6).
- A new application object/action appears after upgrade without policy metadata: manifest and CI validation must default-deny and fail the classification test (Task 4 and Task 10).
- Account switch occurs with an unsaved Designer draft and an active GitHub login: Save/Discard/Cancel must resolve the draft and the login process must never survive the old session (Task 7 and Task 11).

---

### Task 1: Transactional Security Store and Password Primitives

**Files:**
- Create: `web_app/security/__init__.py`
- Create: `web_app/security/store.py`
- Create: `web_app/security/passwords.py`
- Create: `web_app/security/models.py`
- Modify: `requirements.txt`
- Test: `test_security_store.py`

**Interfaces:**
- Produces: `SecurityStore(path: Path)`, `SecurityStore.initialize()`, `SecurityStore.transaction()`, `PasswordHasher.hash_password(str) -> str`, `PasswordHasher.verify_password(str, str) -> bool`, and stable account/group/session Pydantic records.
- Produces schema tables for accounts, credentials, sessions, groups, memberships, capabilities, policy entries, resource ACLs, policy state, audit entries, bootstrap claims, and migration ledger.

- [ ] **Step 1: Write failing schema, UUID, transaction, and Argon2id tests**

```python
def test_security_store_initializes_once_and_rolls_back_failed_transaction(): ...
def test_account_storage_identity_is_uuid_not_username(): ...
def test_argon2id_hash_never_contains_password_and_verifies(): ...
def test_foreign_keys_reject_orphan_membership(): ...
```

- [ ] **Step 2: Run the focused tests and confirm they fail because `web_app.security` does not exist**

Run: `python -m unittest test_security_store.py -v`
Expected: import failure for `web_app.security`.

- [ ] **Step 3: Implement the minimal versioned SQLite store and Argon2id wrapper**

Pin `argon2-cffi>=23,<26`; enable foreign keys; expose explicit transaction context; store timestamps in UTC; validate username casefold uniqueness separately from account UUID.

- [ ] **Step 4: Run focused tests and dependency validation**

Run: `python -m unittest test_security_store.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add requirements.txt web_app/security test_security_store.py
git commit -m "feat(security): add transactional identity store"
```

### Task 2: Administrator Bootstrap, Login, and Server-Side Sessions

**Files:**
- Create: `web_app/security/accounts.py`
- Create: `web_app/security/sessions.py`
- Create: `web_app/security/bootstrap.py`
- Modify: `web_app/models.py`
- Modify: `web_app/app.py`
- Modify: `run_web.ps1`
- Test: `test_accounts.py`
- Test: `test_auth_api.py`

**Interfaces:**
- Consumes: `SecurityStore`, `PasswordHasher` from Task 1.
- Produces: `AccountService`, `SessionService`, `BootstrapService`, `SessionPrincipal`, bootstrap/login/logout/reauthentication/account-enrollment API models, and hashed-cookie session lookup.

- [ ] **Step 1: Write failing bootstrap and session lifecycle tests**

```python
def test_bootstrap_claim_is_one_time_expiring_and_creates_administrator_in_all_groups(): ...
def test_login_rotates_session_and_cookie_contains_no_account_identity(): ...
def test_idle_absolute_expiry_logout_all_and_password_reset_revoke_sessions(): ...
def test_admin_enrollment_claim_lets_user_choose_password(): ...
def test_last_administrator_cannot_be_suspended_or_demoted(): ...
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_accounts.py test_auth_api.py -v`
Expected: missing services/routes.

- [ ] **Step 3: Implement account bootstrap and session APIs**

Use an expiring hashed console claim; never place it in a URL. Create `Administrator` with a stable UUID and all base memberships. Sessions store only token hashes and expose HttpOnly/SameSite cookies. Add throttled login, recent reauthentication, enrollment/reset claims, session listing/revocation, and last-admin transaction guards.

- [ ] **Step 4: Verify GREEN and launcher behavior**

Run: `python -m unittest test_security_store.py test_accounts.py test_auth_api.py test_run_web.py -v`
Expected: all tests pass; launcher prints a claim only when bootstrap is pending.

- [ ] **Step 5: Commit**

```powershell
git add web_app/security web_app/models.py web_app/app.py run_web.ps1 test_accounts.py test_auth_api.py test_run_web.py
git commit -m "feat(auth): add local account bootstrap and sessions"
```

### Task 3: Loopback Middleware, CSRF, Origin, Host, and WebSocket Enforcement

**Files:**
- Create: `web_app/security/http.py`
- Create: `web_app/security/context.py`
- Modify: `web_app/app.py`
- Modify: `run_web.ps1`
- Modify: `web_app/terminal.py`
- Test: `test_security_http.py`
- Test: `test_terminal.py`

**Interfaces:**
- Consumes: `SessionService` from Task 2.
- Produces: `AuthContext(account_id: UUID, session_id: UUID, policy_epoch: int, recent_auth_at: datetime)`, `require_auth_context(request)`, CSRF issue/verify helpers, and WebSocket authentication/epoch checks.

- [ ] **Step 1: Write failing Host/Origin/CSRF/cookie/WebSocket/revocation tests**

```python
def test_non_loopback_host_and_unapproved_origin_are_rejected(): ...
def test_mutation_requires_session_bound_csrf_token(): ...
def test_websocket_closes_when_session_or_policy_epoch_is_revoked(): ...
def test_revocation_during_effect_prevents_commit(): ...
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_security_http.py test_terminal.py -v`
Expected: requests currently bypass security middleware.

- [ ] **Step 3: Implement middleware and account-bound WebSocket context**

Allow only configured loopback hosts, validate Origin, derive account only from the session cookie, bind CSRF to the session, and provide an epoch recheck hook for long-running effects. Refuse non-loopback production binding in the launcher.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest test_security_http.py test_terminal.py test_run_web.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/security web_app/app.py web_app/terminal.py run_web.ps1 test_security_http.py test_terminal.py test_run_web.py
git commit -m "feat(security): enforce localhost account sessions"
```

### Task 4: Central Capability Catalog and Policy Engine

**Files:**
- Create: `web_app/security/capabilities.py`
- Create: `web_app/security/policy.py`
- Create: `web_app/security/route_policy.py`
- Modify: `web_app/app.py`
- Modify: `web_app/designer/components.py`
- Test: `test_policy.py`
- Test: `test_route_policy.py`

**Interfaces:**
- Consumes: `AuthContext`, security records, and transactions.
- Produces: `CapabilityCatalog`, `PolicyEngine.decide(context, resource, action, scope) -> PolicyDecision`, `@requires_capability(action, resolver)`, base-group seed grants, policy epochs, and route/command classification inspection.

- [ ] **Step 1: Write failing grant/deny/invariant/delegation/catalog tests**

```python
def test_explicit_deny_overrides_direct_and_group_grants(): ...
def test_unknown_action_and_new_component_property_default_deny(): ...
def test_protected_invariant_blocks_even_administrator(): ...
def test_actor_cannot_delegate_beyond_own_scope(): ...
def test_every_route_websocket_and_designer_command_is_classified(): ...
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_policy.py test_route_policy.py -v`
Expected: policy types and catalog missing.

- [ ] **Step 3: Implement policy evaluation and classification registry**

Seed immutable group IDs `preferences`, `user`, `designer`, `admin`, and `developer`; no nested groups. Add explicit shared-publish, permission-delegate, preview-as, and destructive-Git capabilities. Advance policy epoch transactionally on membership/policy changes.

- [ ] **Step 4: Classify existing routes and verify GREEN**

Apply resource resolvers to existing HTTP/WebSocket operations without broad wildcard grants. Run: `python -m unittest test_policy.py test_route_policy.py test_web_api.py -v`
Expected: every route is classified and tests pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/security web_app/app.py web_app/designer/components.py test_policy.py test_route_policy.py test_web_api.py
git commit -m "feat(policy): enforce capability-based authorization"
```

### Task 5: Tamper-Evident Audit and Fixed Recovery Services

**Files:**
- Create: `web_app/security/audit.py`
- Create: `web_app/security/recovery.py`
- Create: `web/recovery.html`
- Create: `web/recovery.js`
- Create: `web/recovery.css`
- Modify: `web_app/app.py`
- Modify: `run_web.ps1`
- Test: `test_security_audit.py`
- Test: `test_recovery.py`

**Interfaces:**
- Consumes: `SecurityStore`, `AuthContext`, `PolicyEngine`.
- Produces: `AuditService.append(...)`, `AuditService.verify_chain()`, `RecoveryService`, backup-before-mutation operations, and fixed authenticated recovery routes.

- [ ] **Step 1: Write failing audit/recovery tests**

```python
def test_security_mutation_and_audit_entry_commit_or_rollback_together(): ...
def test_audit_chain_detects_tampering_and_redacts_sensitive_fields(): ...
def test_break_glass_claim_is_local_one_time_and_never_auto_grants_admin(): ...
def test_recovery_can_quarantine_overlay_and_restore_verified_backup(): ...
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_security_audit.py test_recovery.py -v`
Expected: missing audit/recovery services.

- [ ] **Step 3: Implement transactional audit and bounded recovery**

Hash-chain canonical audit records. Recovery can inspect migration health, revoke sessions, quarantine overlays, revert published revisions, recover an Administrator through a claim, and restore verified backup only. Keep this UI independent of Designer assets.

- [ ] **Step 4: Verify GREEN and static safety**

Run: `python -m unittest test_security_audit.py test_recovery.py test_web_static.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/security web/recovery.* web_app/app.py run_web.ps1 test_security_audit.py test_recovery.py test_web_static.py
git commit -m "feat(security): add audited recovery controls"
```

### Task 6: Resource Ownership and Crash-Safe Migration

**Files:**
- Create: `web_app/security/resources.py`
- Create: `web_app/security/migration.py`
- Modify: `web_app/workspace.py`
- Modify: `web_app/settings.py`
- Modify: `web_app/conversation.py`
- Modify: `web_app/artifacts.py`
- Modify: `web_app/skills.py`
- Modify: `web_app/model_run_store.py`
- Modify: `web_app/designer/store.py`
- Test: `test_account_migration.py`
- Test: `test_resource_ownership.py`

**Interfaces:**
- Consumes: `SecurityStore`, `AuditService`, Administrator UUID.
- Produces: `ResourceRef(kind, id, owner_id, visibility)`, `ResourceService.authorize_path(...)`, `AccountMigration.run()`, verified backups, migration ledger, UUID account roots, shared resource markers.

- [ ] **Step 1: Write failing classification, path, and interruption tests**

```python
def test_legacy_personal_data_migrates_to_administrator_and_shared_catalogs_remain_shared(): ...
def test_migration_resumes_after_crash_without_mixed_ownership(): ...
def test_reparse_or_symlink_escape_and_cross_account_identifier_are_rejected(): ...
def test_same_checkout_path_alias_resolves_to_one_acl_resource(): ...
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_account_migration.py test_resource_ownership.py -v`
Expected: missing ownership/migration services.

- [ ] **Step 3: Implement classification table, backups, ledger, and ownership adapters**

Follow the spec's resource table exactly. Preserve stable IDs, use UUID directories, protect against reparse traversal, and refuse unsafe downgrade. Do not migrate global GitHub credentials.

- [ ] **Step 4: Verify GREEN and existing store compatibility**

Run: `python -m unittest test_account_migration.py test_resource_ownership.py test_settings.py test_conversation.py test_artifacts.py test_skills.py test_model_run_store.py test_designer_store.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/security web_app/workspace.py web_app/settings.py web_app/conversation.py web_app/artifacts.py web_app/skills.py web_app/model_run_store.py web_app/designer/store.py test_account_migration.py test_resource_ownership.py
git commit -m "feat(accounts): migrate resources to explicit ownership"
```

### Task 7: Login, Enrollment, Account Administration, and Switching UI

**Files:**
- Create: `web/auth.js`
- Create: `web/auth.css`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/app.css`
- Modify: `web/ui_bootstrap.js`
- Test: `test_auth_web.py`
- Test: `test_web_static.py`

**Interfaces:**
- Consumes: auth/account/group/policy APIs from Tasks 2–4.
- Produces: fixed account chrome, bootstrap/login/enrollment/reauthentication views, account/group/session administration, active account indicator, switch/logout behavior, and CSRF-aware request wrapper.

- [ ] **Step 1: Write failing static/client contract tests**

```python
def test_protected_workspace_never_renders_before_session_check(): ...
def test_account_switch_clears_content_and_requires_new_login(): ...
def test_admin_ui_exposes_effective_access_sources_and_last_admin_warning(): ...
def test_browser_storage_keys_contain_no_session_or_cross_account_identity_data(): ...
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_auth_web.py test_web_static.py -v`
Expected: missing auth client.

- [ ] **Step 3: Implement fixed account chrome and administration flows**

Render active local account separately from provider identity. On switch, resolve draft Save/Discard/Cancel through registered guards, clear protected DOM first, logout, then show login. Broadcast revocation across tabs.

- [ ] **Step 4: Verify GREEN and JavaScript syntax**

Run: `python -m unittest test_auth_web.py test_web_static.py -v; node --check web/auth.js; node --check web/app.js`
Expected: tests and syntax checks pass.

- [ ] **Step 5: Commit**

```powershell
git add web/auth.js web/auth.css web/index.html web/app.js web/app.css web/ui_bootstrap.js test_auth_web.py test_web_static.py
git commit -m "feat(web): add local account experience"
```

### Task 8: Account-Scoped GitHub CLI and Git Execution

**Files:**
- Create: `web_app/security/subprocess_env.py`
- Create: `web_app/account_git.py`
- Modify: `web_app/github_auth.py`
- Modify: `web_app/github_cli.py`
- Modify: `web_app/git_broker.py`
- Modify: `web_app/models.py`
- Modify: `web_app/app.py`
- Test: `test_account_git.py`
- Test: `test_github_auth.py`
- Test: `test_github_cli.py`
- Test: `test_git_broker.py`

**Interfaces:**
- Consumes: `AuthContext`, `PolicyEngine`, `ResourceService`, `AuditService`.
- Produces: `AccountSubprocessEnvironment.build(account_id, purpose)`, `AccountGitService`, account-bound login sessions, `GH_CONFIG_DIR`, expected GitHub identity binding, canonical checkout ACLs, and per-repository mutation locks.

- [ ] **Step 1: Write and run the real-process GitHub credential-isolation spike**

Test separate temporary `GH_CONFIG_DIR` roots against installed `gh` without logging in or copying credentials. Record whether Windows keyring lookup is config/account separable. Expected: a verified supported isolation mode or a fail-closed unavailable result; never machine-global fallback.

- [ ] **Step 2: Write failing account-bound environment and concurrency tests**

```python
def test_ambient_tokens_hosts_helpers_and_ssh_agent_are_not_inherited(): ...
def test_login_process_is_bound_to_account_session_and_cancelled_on_logout(): ...
def test_expected_github_host_and_identity_are_rechecked_at_commit(): ...
def test_shared_checkout_aliases_serialize_mutation_and_recheck_policy_epoch(): ...
```

- [ ] **Step 3: Implement the account GitHub/Git service**

Construct an allow-listed environment, pin github.com and expected identity, keep device codes session-private, and terminate→wait→kill→wait subprocesses on cancellation. Run Git noninteractively and fail closed if account-owned credentials are unavailable.

- [ ] **Step 4: Verify focused GitHub/Git tests**

Run: `python -m unittest test_account_git.py test_github_auth.py test_github_cli.py test_git_broker.py -v`
Expected: all tests pass, including revocation and race fixtures.

- [ ] **Step 5: Commit**

```powershell
git add web_app/security/subprocess_env.py web_app/account_git.py web_app/github_auth.py web_app/github_cli.py web_app/git_broker.py web_app/models.py web_app/app.py test_account_git.py test_github_auth.py test_github_cli.py test_git_broker.py
git commit -m "feat(git): isolate GitHub and Git by account"
```

### Task 9: Immutable Overlay Store and Policy-Aware Composition

**Files:**
- Create: `web_app/designer/overlays.py`
- Create: `web_app/designer/composition.py`
- Create: `web_app/designer/permissions.py`
- Modify: `web_app/designer/contracts.py`
- Modify: `web_app/designer/store.py`
- Modify: `web_app/app.py`
- Test: `test_designer_overlays.py`
- Test: `test_designer_permissions.py`

**Interfaces:**
- Consumes: `PolicyEngine`, `AuditService`, ownership records, existing scene contracts.
- Produces: `OverlayStore`, immutable `OverlayRevision`, `OverlayComposer.compose(base, shared, groups, personal, context)`, stable object/property IDs, tombstones, group priority, quarantine, validate/publish/rollback APIs.

- [ ] **Step 1: Write failing composition/publication tests**

```python
def test_overlay_order_is_base_shared_priority_groups_personal(): ...
def test_denied_or_unknown_operation_quarantines_layer_without_partial_apply(): ...
def test_publish_requires_recent_auth_audience_preview_and_optimistic_digest(): ...
def test_deleted_object_id_becomes_tombstone_and_is_not_reused(): ...
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_designer_overlays.py test_designer_permissions.py -v`
Expected: missing overlay services.

- [ ] **Step 3: Implement immutable overlays and deterministic composition**

Validate each operation against component schema and effective policy at load and publication. Store personal/group/shared drafts separately; audit shared/group publication and rollback transactionally.

- [ ] **Step 4: Verify GREEN with existing Designer tests**

Run: `python -m unittest test_designer_overlays.py test_designer_permissions.py test_designer_contracts.py test_designer_store.py test_designer_commands.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add web_app/designer web_app/app.py test_designer_overlays.py test_designer_permissions.py
git commit -m "feat(designer): add permission-aware UI overlays"
```

### Task 10: Complete the Designer Shell and Application Manifests

**Files:**
- Create: `web/designer.html`
- Create: `web/designer_app.js`
- Create: `web/designer.css`
- Create: `web/designer_renderer.js`
- Modify: `web/designer_commands.js`
- Modify: `web/designer_model.js`
- Modify: `web_app/designer/json_codr_manifest.py`
- Modify: `web_app/designer/components.py`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Test: `test_designer_web.py`
- Test: `test_designer_commands.py`
- Test: `test_designer_components.py`

**Interfaces:**
- Consumes: overlay APIs, policy inspection, existing scene/command/component contracts.
- Produces: Designer route, page/layer/component panels, direct canvas selection, inspector sections, effective-permission display, preview-as, personal/shared modes, save/publish/export, draft switch guard, and stable manifests for every JSON_CODR page.

- [ ] **Step 1: Write failing shell, manifest, permission, and draft tests**

```python
def test_every_application_page_has_stable_object_and_property_ids(): ...
def test_new_unclassified_manifest_action_fails_validation(): ...
def test_inspector_only_emits_commands_allowed_by_effective_policy(): ...
def test_account_switch_offers_save_discard_cancel_for_unsaved_draft(): ...
def test_recovery_identity_and_permission_invariants_are_not_overlay_nodes(): ...
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_designer_web.py test_designer_commands.py test_designer_components.py -v`
Expected: shell/manifests incomplete.

- [ ] **Step 3: Implement the Designer shell using existing serializable commands**

Use the renderer for a script-isolated canvas. Keep application customization and project mode. Expose Content, Layout, Style, Typography, Asset, Actions, Accessibility, Permissions, and Advanced inspectors. Preserve keyboard operation and responsive breakpoints.

- [ ] **Step 4: Verify GREEN and JavaScript syntax**

Run: `python -m unittest test_designer_web.py test_designer_commands.py test_designer_components.py test_designer_contracts.py -v; node --check web/designer_app.js; node --check web/designer_renderer.js; node --check web/designer_commands.js; node --check web/designer_model.js`
Expected: tests and syntax checks pass.

- [ ] **Step 5: Commit**

```powershell
git add web/designer* web/index.html web/app.js web_app/designer test_designer_web.py test_designer_commands.py test_designer_components.py
git commit -m "feat(designer): add account-aware visual editor"
```

### Task 11: Create and Validate the Dual UI-Design Skills

**Files:**
- Create: `C:/Users/Jason.Hensz/.codex/skills/design-ui-workspaces/SKILL.md`
- Create: `C:/Users/Jason.Hensz/.codex/skills/design-ui-workspaces/agents/openai.yaml`
- Create: `skills/design-ui-workspaces/SKILL.md`
- Modify: `test_skills.py`
- Test: `test_ui_design_skill.py`

**Interfaces:**
- Consumes: Designer object/capability model and Source Control design.
- Produces: matching concise methodology for Codex and JSON_CODR native envelope; triggers for programs, websites, modules, page/section/object refactors, responsive/accessibility design, and permission-aware functional flows.

- [ ] **Step 1: Initialize the Codex skill with the skill-creator script and generated interface metadata**

Use `init_skill.py design-ui-workspaces --path C:/Users/Jason.Hensz/.codex/skills --resources references` only if the folder does not already exist. Read `references/openai_yaml.md` before generating UI metadata.

- [ ] **Step 2: Write failing parity and native-envelope tests**

```python
def test_codex_and_json_codr_skills_share_required_workflow_sections(): ...
def test_native_skill_has_schema_one_envelope_and_arguments_syntax(): ...
def test_skill_requires_object_map_permissions_responsive_and_visual_verification(): ...
```

- [ ] **Step 3: Write both skills and validate them**

Keep the canonical workflow concise; move detailed checklists to one-level references only when needed. Run `quick_validate.py` on the Codex skill and JSON_CODR envelope validation through project tests.

- [ ] **Step 4: Forward-test against Settings with a fresh agent**

Give only the skill path and a Settings-page redesign request. Success: valid object/capability map, responsive proposal, accessibility checks, protected invariants, and verification checklist without design-document leakage. Remove disposable outputs afterward.

- [ ] **Step 5: Commit repository skill and tests**

```powershell
git add skills/design-ui-workspaces/SKILL.md test_ui_design_skill.py test_skills.py
git commit -m "feat(skills): add permission-aware UI design workflow"
```

### Task 12: Refactor the Source Control Workspace with the New Skill

**Files:**
- Create: `web/source_control.css`
- Create: `web/source_control.js`
- Modify: `web/source-control.html`
- Modify: `web/source_control_updates.js`
- Modify: `web_app/designer/json_codr_manifest.py`
- Modify: `web_app/app.py`
- Test: `test_source_control_web.py`
- Test: `test_web_static.py`
- Test: `test_github_cli.py`

**Interfaces:**
- Consumes: account client, account Git service, overlay/Designer manifests, `design-ui-workspaces` skill.
- Produces: compact account-aware connector, searchable repository selection, local/remote comparison, one check/update action, Activity/Pull Requests/Releases/Advanced progressive disclosure, responsive Source Control manifest objects.

- [ ] **Step 1: Use the UI skill to produce the object/capability map and failing UI tests**

```python
def test_source_control_primary_card_has_distinct_local_and_github_identity(): ...
def test_repository_search_handles_large_lists_without_unbounded_dom(): ...
def test_primary_action_transitions_current_behind_confirm_update_current(): ...
def test_advanced_operations_remain_available_by_capability(): ...
def test_mobile_layout_has_no_horizontal_overflow_contract(): ...
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest test_source_control_web.py test_web_static.py -v`
Expected: compact structure/search/manifests missing.

- [ ] **Step 3: Split inline page code and implement the compact workspace**

Keep account and GitHub identity visibly separate. Render bounded repository results, exact commit/status details, last-check time, and progressive sections. Preserve confirmation, stale-generation, path, identity, and exact-SHA guards.

- [ ] **Step 4: Verify GREEN and responsive static behavior**

Run: `python -m unittest test_source_control_web.py test_web_static.py test_github_cli.py test_github_auth.py test_git_broker.py -v; node --check web/source_control.js; node --check web/source_control_updates.js`
Expected: tests and syntax checks pass.

- [ ] **Step 5: Commit**

```powershell
git add web/source-control.html web/source_control.css web/source_control.js web/source_control_updates.js web_app/designer/json_codr_manifest.py web_app/app.py test_source_control_web.py test_web_static.py
git commit -m "feat(source-control): add account-aware editable workspace"
```

### Task 13: Full Verification, Migration Drill, Live Reload, and Delivery

**Files:**
- Modify: `README.md`
- Modify: `CONTINUE_UI_DESIGNER.md`
- Modify: version-bearing files identified by `test_version.py`
- Test: full repository suite and live browser.

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: verified upgrade/recovery documentation, release version consistency, pushed branch, updated pull request, and live localhost instance.

- [ ] **Step 1: Run security and migration acceptance matrices**

Run focused auth/policy/audit/recovery/migration/GitHub/Designer/Source Control tests, including interruption, revocation mid-operation, cross-account path aliases, account switching, and overlay corruption.
Expected: zero failures.

- [ ] **Step 2: Run complete automated verification**

Run: `python -m unittest discover -v`
Expected: zero unexpected failures; document only confirmed pre-existing environment skips.

Run: `node --check web/app.js; node --check web/auth.js; node --check web/designer_app.js; node --check web/designer_renderer.js; node --check web/source_control.js; git diff --check`
Expected: all checks exit zero.

- [ ] **Step 3: Perform a clean migration and recovery drill**

Copy a representative pre-account data root, initialize Administrator through a one-time claim, migrate, interrupt/resume once, verify ownership, quarantine a corrupt overlay, restore a verified revision, and confirm machine-global GitHub credentials were untouched.

- [ ] **Step 4: Verify live UI in the in-app browser**

Restart the localhost application. Verify bootstrap/login, Administrator group membership, account creation/enrollment, account switch, per-account GitHub prompt, Source Control desktop/tablet/mobile layouts, Designer object selection and permissions, shared publication preview, safe mode, no console errors, and no horizontal overflow.

- [ ] **Step 5: Commit, push, synchronize, and reload live**

```powershell
git add README.md CONTINUE_UI_DESIGNER.md <version-files>
git commit -m "docs: publish account-aware designer workflow"
git push origin codex/hybrid-zero-layer-ui-designer
git pull --ff-only
```

Confirm the remote SHA matches local, update the open pull request description with security/migration/verification results, restart the application, and repeat the final health and browser checks.
