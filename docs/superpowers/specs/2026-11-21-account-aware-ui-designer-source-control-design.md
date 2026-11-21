# Account-Aware UI Designer and Source-Control Workspace Design

## Intent

Turn JSON_CODR's existing structured UI Designer into the shared, account-aware system for customizing JSON_CODR and authoring project interfaces. The first complete application surface is a compact GitHub and Git workspace that makes account, repository, branch, checkout, and update state easy to understand while retaining advanced operations through progressive disclosure.

The system must let authorized users change individual pages, sections, headings, layouts, color schemes, sizing, styles, and approved functional flows by selecting the corresponding design object. Access is not a binary locked/unlocked flag: every object and capability is governed by local account groups, resource ownership, and explicit policy.

## Threat Model and Deployment Boundary

The first release is localhost-only and protects accounts from accidental or unauthorized cross-use inside JSON_CODR. It does not claim to isolate mutually hostile people who share the same Windows login, local filesystem access, process-debugging ability, or malware exposure. Stronger isolation requires separate operating-system accounts or a future network/server deployment.

The server must:

- bind only IPv4 and IPv6 loopback interfaces;
- reject unapproved `Host` headers and non-loopback startup outside explicit development mode;
- validate `Origin` for HTTP mutations and WebSocket connections;
- use server-side sessions with `HttpOnly`, `SameSite=Strict` cookies and CSRF protection;
- keep credentials, session tokens, and authorization state out of browser storage;
- document the residual same-Windows-user risk plainly.

Remote and LAN access, federation, SSO, TLS termination, and hostile multi-tenant isolation are deferred.

## Goals

- Add local accounts with secure authentication, server-side sessions, suspension, session revocation, and recent reauthentication for sensitive operations.
- Create the first account as `Administrator` through a one-time local bootstrap and enroll it in all base groups.
- Provide immutable-ID base groups for Preferences, User, Designer, Admin, and Developer capability bundles.
- Evaluate authorization per subject, resource, action, and scope, with backend enforcement for every API, WebSocket message, background effect, export, and Designer command.
- Classify existing data as system-global, shared, or account-owned and migrate it safely.
- Support personal, group, and shared UI overlays with deterministic composition, immutable revisions, preview, publication, rollback, and recovery.
- Complete the Designer shell around the existing scene document, component registry, and reversible command engine.
- Make individual UI objects editable according to policy, including content, typography, color, spacing, sizing, layout, visibility, assets, accessibility, and approved actions.
- Refactor the GitHub/Git workspace into a compact daily workflow with advanced tools behind tabs or accordions.
- Isolate GitHub CLI configuration and Git execution context by local account and prompt each user to connect GitHub only when required.
- Create one reusable UI-design method and package it as both a Codex skill and a provider-neutral JSON_CODR native skill.
- Preserve a fixed recovery surface outside editable overlays.

## Non-goals

- Network-accessible accounts or remote administration.
- Protection from the owner of the same Windows account or machine administrator.
- Arbitrary JavaScript, shell commands, or live-DOM mutation through the Designer.
- Automatic migration of existing machine-global GitHub credentials into an account.
- Treating Developer membership as unrestricted host-filesystem access.
- Making visual hiding or disabled controls count as authorization.
- Replacing GitHub CLI, Git, FastAPI, or the structured scene model.

## Anti-goals

- Default passwords, automatic Administrator login, or hidden bypass accounts.
- Username-based storage paths or security identifiers.
- Process-global GitHub identity in an account-aware interface.
- Permission rules that fail open for unknown routes, objects, properties, or actions.
- An overlay that can remove recovery, disguise active identity, or bind an innocent control to a privileged effect.
- A last-administrator deletion or demotion that leaves no verified recovery-capable administrator.
- Client-side undo/redo being treated as durable recovery or audit history.

## Approaches Considered

### Compact workspace plus shared structured Designer — selected

Complete the current scene-based Designer and use it for both JSON_CODR customization and project authoring. Refactor Source Control into one compact connection/status surface with Activity, Pull Requests, Releases, and Advanced areas beneath it. Apply account policy to the same object model.

This approach reuses the existing component registry, scene validation, reversible commands, responsive overrides, and protected manifest concept. It avoids creating separate page-builder and application-customization systems.

### Separate daily Source Control and administration pages

Move everyday checking and updates to a dedicated page and keep repository administration on a second route. This produces the cleanest isolated workflow but introduces additional navigation and does not solve object-level editing across the rest of JSON_CODR.

### Incremental restyle of the existing page

Add collapsible sections, search, and better cards without completing the shared Designer or identity model. This is lower effort but leaves the long page architecture, global credential state, and binary protection model intact.

## Security and Identity Architecture

### Persistence

Use a transactional SQLite security store separate from user content. Enable foreign keys and explicit schema migrations. Security-sensitive records use stable UUIDs and include creation/update timestamps and version fields.

The store contains accounts, credential records, sessions, groups, memberships, capability definitions, grants and denials, resource ACLs, policy epochs, recent-reauthentication state, audit entries, and migration ledger records. Passwords use Argon2id through a pinned, maintained password-hashing dependency. Raw passwords, session tokens, CSRF secrets, GitHub tokens, and device codes are never logged.

### First-run bootstrap

No default password or automatic session is created. On an uninitialized store, the launcher emits a one-time, expiring claim code and the loopback application exposes only the bootstrap enrollment route plus static recovery styling. The user types the claim code, chooses the `Administrator` password, and receives a rotated authenticated session. The claim is stored hashed, consumed once, expires quickly, and is idempotently recoverable after a crash without creating a second Administrator.

The `Administrator` account has a stable UUID, the initial username `Administrator`, and membership in every base group. Username changes never move account-owned storage.

After bootstrap, an Admin creates a pending account with Preferences and User membership by default. The new user redeems a one-time, expiring enrollment claim and chooses their own password; the Admin never chooses or sees it. Self-service password change requires the current password. An Admin-initiated forgotten-password reset revokes existing sessions and issues a new one-time enrollment claim. Account creation, enrollment, reset, suspension, deletion, and membership changes are audited.

### Session lifecycle

Sessions use high-entropy random bearer tokens stored only in secure cookies; the database stores token hashes. Login rotates the session identifier. Sessions have idle and absolute expiration, record a policy epoch, and support per-session revoke, logout-all, account suspension, password change, and account deletion subject to last-administrator invariants.

Sensitive actions require recent password reauthentication: account/group/policy changes, shared overlay publication, recovery, GitHub disconnect, destructive GitHub actions, and permission delegation. Login throttling is keyed conservatively to account and loopback client context without creating an account-enumeration oracle.

Logout, suspension, password reset, group changes, and policy changes invalidate affected sessions or their policy epochs, close WebSockets, cancel account-bound login subprocesses, and reauthorize or cancel sensitive background work.

Account switching means ending the current browser session, clearing all account-bound content and non-sensitive cached state, and returning to login for the next account. One browser profile does not keep multiple simultaneously selectable JSON_CODR identities. Other independent browser sessions may remain active according to normal concurrent-session policy.

### Base groups

Base groups have immutable identifiers and editable display descriptions. They are not nested in the first release.

| Stable ID | Default responsibility |
| --- | --- |
| `preferences` | Own theme, color, density, typography, accessibility, and personal preference overlay. |
| `user` | Ordinary account-owned conversations, projects, attachments, and explicitly granted workspaces. |
| `designer` | Author personal designs and drafts; edit eligible content/layout/style/actions; publish only with a separate grant. |
| `admin` | Manage accounts, memberships, policy, recovery, audit viewing/export, system settings, and shared-overlay approval. |
| `developer` | Use explicitly granted terminal, files, Git, source-backed components, schemas, and code-validation capabilities. |

Membership alone does not grant arbitrary resources. Shared publication, impersonation/preview, permission delegation, destructive source-control actions, and break-glass recovery are distinct capabilities.

New accounts receive Preferences and User only. Designer, Admin, and Developer membership must be granted explicitly by an authorized Admin. Base group definitions may evolve through versioned migrations, but their stable identifiers and protected minimum/maximum boundaries cannot be repurposed.

### Policy model

Every decision is expressed as subject, resource, action, and scope. Examples include:

- `overlay.personal.style` on own page objects;
- `overlay.shared.publish` on a named application page;
- `designer.node.action.set` on a specific object type;
- `git.repository.read` and `git.checkout.update` on an explicit repository/path grant;
- `account.session.revoke` on own or managed accounts.

Direct and group grants are combined, explicit denial overrides grants, and protected invariants outrank every grant including Administrator. Unknown resources, actions, object types, properties, and routes default-deny. Nested groups are not supported initially. Actors cannot delegate capabilities they do not possess at an equal or broader scope.

The server owns one versioned capability/resource catalog and one central `AuthContext` and policy engine. Every route, WebSocket message, service entry point, background effect, subprocess, export, and Designer command must declare a catalog rule. CI fails when an endpoint or command is unclassified.

Authorization is rechecked at effect/commit time. A monotonically increasing policy epoch invalidates stale decisions and caches. The active account is derived only from the authenticated server session, never from request body account IDs.

### Protected invariants

Permissions are granular, but some invariants cannot be granted away:

- login, logout, account switch, active-account identity, active-GitHub identity, recovery entry, and safe-mode controls remain available in fixed application chrome;
- the last effective recovery-capable Administrator cannot be deleted, suspended, or demoted without verifying another in the same transaction;
- confirmation meaning, permission warnings, repository/path/branch scope, safety status, and audit/recovery controls cannot be hidden or misleadingly relabeled;
- a visual action cannot invoke a capability the actor lacks;
- safe mode bypasses overlays, never authentication or authorization.

## Resource Ownership and Migration

Every existing store is classified before account enforcement is enabled: settings, chats, attachments, model runs, terminal sessions, Designer projects/assets/drafts, skills, skillsets, workspace grants, repositories, benchmark results, logs, and background tasks.

Initial classification is explicit:

| Resource | Classification |
| --- | --- |
| Application version, capability catalog, component registry, base manifests, provider/runtime inventory | System-global, read according to capability. |
| Installed skills, generated skillsets, model catalog, benchmark definitions, approved shared templates | Shared; mutation requires scoped Admin or Developer capability. |
| Global defaults, recovery state, policy, groups, audit configuration, migration ledger | System-global Admin resources. |
| Existing chats, attachments, personal settings, model runs, terminals, Designer projects/drafts/assets, repository choices, and workspace grants | Migrated to initial Administrator ownership unless an explicit shared marker exists. |
| Benchmark results and sanitized operational health history | Shared read, Admin-managed retention; actor provenance retained when known. |
| Repository checkouts | Administrator-owned initially; later sharing requires an explicit path grant and ACL. |
| Security audit | System-global append-only; authorized Admin read/export only. |

Resources are system-global, intentionally shared, or account-owned. Account-owned files use UUID directories with restrictive filesystem ACLs, symlink/reparse-point protection, bounded quotas, and atomic writes. Identifiers are non-enumerating and ownership checks occur below the HTTP layer.

The migration is versioned, idempotent, crash-resumable, and ledgered. It creates a verified backup before changing ownership. Existing personal data is assigned to the initial Administrator unless explicitly defined as system-global or shared. Stable IDs are preserved where safe. Failed migration leaves the old application data untouched and starts in recovery mode. Downgrade to a version that would ignore account controls is refused.

Existing machine-global GitHub credentials are not copied or reassigned. Administrator reconnects GitHub inside the new account scope.

## Audit and Recovery

Security audit records are append-only and hash-chained. They contain actor UUID, session/correlation ID, target resource, action, policy and revision digests, decision/result, reason code, and timestamp. They never contain passwords, tokens, cookies, device codes, or unsanitized command output.

Authentication events, credential/session changes, memberships, policy mutations, shared-overlay publication, recovery, GitHub connect/disconnect, Git effects, sensitive denials, and break-glass actions are audited. Account, policy, shared-overlay, recovery, and destructive Git changes commit with their audit event or fail closed. Rotation and export preserve chain verification; only authorized Admin users may view or export security audit data.

The fixed recovery surface is bundled, keyboard accessible, visually unmistakable, independent of external assets, and outside overlays. A local-console break-glass claim can disable or quarantine overlays, revert a published revision, revoke sessions, recover an Administrator, restore a verified backup, and inspect migration health. It creates a backup before mutation and never silently grants Admin. Recovery actions are audited.

## Account-Scoped GitHub and Git

Each local account receives a generated GitHub configuration root and an allow-listed subprocess environment. GitHub login processes are bound to account UUID, session, CSRF context, and a single login generation. They are cancelled on logout, account switch, expiry, shutdown, or revocation. Device codes and sanitized status are visible only to the initiating session.

Before claiming account isolation, an implementation spike must prove how the installed GitHub CLI combines `GH_CONFIG_DIR` with Windows Credential Manager for multiple accounts. If platform credential storage cannot be safely separated, the connector must fail closed or use an explicitly account-scoped supported storage mode protected by restrictive ACLs; it must not silently fall back to machine-global credentials.

Every GitHub invocation pins the host and expected authenticated identity. The constructed environment removes inherited `GH_TOKEN`, `GITHUB_TOKEN`, `GH_HOST`, credential-helper overrides, and other ambient credential variables unless they are explicitly account-owned.

Git execution also uses an account-scoped allow-listed environment. Global Git credential helpers, SSH agents, and global configuration are not implicitly trusted. Remote operations are noninteractive and fail closed when account-owned credentials are unavailable. GitHub identity and local Git author identity are displayed separately.

Local checkouts are account-owned or explicitly shared. Canonical paths require per-account grants; shared repositories carry ACLs and serialize mutations. Developer membership does not grant arbitrary filesystem access.

## Overlay and Designer Architecture

### Composition

The effective scene is composed deterministically:

1. signed base manifest;
2. one published system/shared overlay revision for the page;
3. applicable group overlays in explicit stable priority order;
4. the signed-in account's personal overlay.

Every layer references stable page, object, and property identifiers. IDs are independent of DOM position, label text, username, and scene-tree order. Renames use aliases/migrations; deleted IDs become tombstones and are never silently reused.

Conflicts resolve by layer order only after policy validation. Explicit denial prevents a later layer from applying the denied capability. Loading or publishing revalidates every operation against the current manifest, schema, and policy epoch. Invalid layers are quarantined rather than partially applied.

Personal and shared modes are visually distinct. Shared publication requires an audience/effective-permission preview, recent reauthentication, explicit confirmation, optimistic concurrency, and an immutable server-side revision. Drafts are never published implicitly.

A Designer may create a group-overlay draft only for a group and page they are permitted to target. An Admin with `overlay.group.publish` publishes it after audience and effective-permission preview. Group audience is the referenced immutable group ID; group priority is an Admin-managed unique integer with conflict-safe reordering. Changing priority or membership revalidates affected effective scenes and advances the policy epoch.

### Designer experience

Complete the existing Designer around its versioned scene document and reversible command engine:

- top bar: account, editing scope, page, breakpoint, undo/redo, preview, validation, save, publish/export;
- left panel: pages, layers, templates, components, shared assets;
- canvas: direct object selection, multi-select, resize, reorder, bounded freeform movement, stack/grid drop targets, breakpoint bounds;
- right inspector: Content, Layout, Style, Typography, Asset, Actions, Accessibility, Permissions, Advanced;
- status region: save state, policy source, effective permission, conflicts, accessibility issues, announcements.

The permission inspector shows effective access, sources, denials, pending changes, and a policy-authorized preview-as-account mode. It warns about last-administrator and privilege-delegation rules.

All commands are validated server-side against document schema and effective policy. Browser commands remain serializable and reversible, but durable recovery uses immutable server revisions. Unsaved drafts are handled explicitly during account switch; the old account's content is cleared before new-account data is fetched.

When a draft has unsaved client changes, account switching presents Save, Discard, and Cancel. Save persists an account-owned draft revision before logout; Discard removes only the unpersisted client delta; Cancel remains in the current account. An optional autosave preference writes only to the current account's draft and never publishes.

### Editable capabilities

Eligible nodes can expose separate capabilities for content, headings, typography, color tokens, spacing, size, grid/stack/freeform layout, responsive overrides, visibility, assets, duplication, grouping, ordering, deletion, accessibility metadata, and constrained functional actions. The component registry declares which properties and actions exist in JSON_CODR versus project mode.

Functional actions are catalog entries such as navigate, open dialog, switch tab, submit validated form, set value, or invoke an explicitly authorized connector operation. Designs never contain executable functions, arbitrary URLs, shell commands, or string-evaluated code.

## GitHub and Git Workspace Refactor

The first fully covered application page is Source Control.

The release continues to support both Designer modes established by the existing architecture: JSON_CODR application customization and general multi-page project-interface authoring/export. Every JSON_CODR page must expose a stable manifest and base object tree, while Source Control is the first page required to exercise the complete account, permission, overlay, functional-action, and responsive-editing workflow end to end.

### Primary daily workflow

- Compact header with distinct local-account and GitHub-identity indicators.
- Account-scoped searchable repository selector suitable for hundreds of repositories.
- Branch selector with protected/default status and recent choices.
- Local checkout selector/path grant with account ownership or shared ACL status.
- One comparison panel showing local and remote exact commits, cleanliness, ahead/behind state, last check time, and plain-language status.
- One primary button: **Check for updates**. When safely behind, the confirmed flow offers the exact-SHA fast-forward update and reports the result.
- Connection and update operations retain server-side safety revalidation, serialization, and audit.

### Progressive disclosure

Below the primary card, provide Activity, Pull Requests, Releases, and Advanced tabs or accordions. Repository creation/settings, issues, branches, commits, clone, staging, commit, fetch, pull, and push remain available according to policy. Destructive and publishing operations require appropriate capability, recent reauthentication where applicable, explicit confirmation, and audit.

The page remains usable without Designer mode. In Designer mode, stable objects can be selected directly and edited according to policy. Identity, permission, repository scope, confirmation meaning, safety status, and recovery controls retain their protected invariants.

### Responsive behavior

Desktop presents the comparison in one row; tablet stacks identity/scope above status; mobile presents account, repository, branch, checkout, status, and action sequentially with no horizontal overflow. Advanced data lists use bounded tables/cards and pagination rather than rendering unbounded repository history.

## Browser State and Account Switching

Browser state is namespaced by account UUID when it is non-sensitive and cleared on logout/account switch. LocalStorage, IndexedDB, caches, persisted repository/path choices, drafts, and service-worker data cannot leak across accounts. Cross-tab broadcast revokes sessions and clears protected content. Navigation must not flash the previous account's content.

Active local account, effective editing scope, and active GitHub identity remain visible and distinct. Objects without read permission are not disclosed; discoverable but unavailable capabilities may be disabled with an explanation.

## Reusable UI Skills

Create a canonical, concise UI-design workflow covering discovery, design-system extraction, responsive and accessible hierarchy, object-level capability mapping, permission-aware functional flow, visual verification, and regression checks.

Package it twice:

1. a Codex skill under the user's auto-discovered skills directory with `SKILL.md` and matching `agents/openai.yaml`;
2. a provider-neutral JSON_CODR native skill using the version-1 skill envelope and `{{arguments}}` syntax.

The packages share methodology but use their host-specific metadata and safety boundaries. The skill is used to refactor Source Control and its effectiveness is forward-tested on a second representative page without publishing additional product changes.

The forward-test target is the Settings page because it exercises headings, forms, grouped sections, preferences, Admin-only controls, responsive layout, and protected invariants. Success requires the skill to produce a valid object/capability map, responsive design proposal, accessibility checks, permission boundaries, and verification checklist without access to this design document's conclusions. The forward test may create disposable artifacts but does not publish Settings product changes.

## APIs and Service Boundaries

Add central services for accounts, sessions, policy, audit, migration, recovery, resource ownership, overlays, and account-scoped GitHub/Git execution. HTTP handlers remain thin and receive `AuthContext` from middleware.

Representative routes include:

- bootstrap status and claim enrollment;
- login, logout, recent reauthentication, active session, session listing/revocation;
- account and group administration;
- effective-policy inspection and preview;
- personal/group/shared overlay draft, validate, publish, revision, rollback, and quarantine;
- account-scoped GitHub status/login/cancel/logout/repositories/branches;
- existing Source Control operations updated to derive actor and credential context from the server session.

Exact route names are left to the implementation plan, but every route and WebSocket message must reference the capability catalog and declare its resource resolver.

## Failure Behavior

- Unknown account, route, capability, object, property, resource, or policy version fails closed without confirming whether another account owns it.
- Corrupt or unauthorized overlays are quarantined and the base scene loads with a visible diagnostic for authorized users.
- Audit persistence failure blocks security-sensitive mutations.
- Policy epoch mismatch causes reauthorization or cancellation, never continued use of stale rights.
- Account switching clears protected UI before loading the next account and cancels GitHub login, terminal, Git, and other sensitive account-bound effects.
- GitHub credential isolation failure disables per-account connection and explains the local platform limitation.
- Migration interruption resumes from the ledger or restores the verified backup.
- The base application and recovery surface remain usable when Designer data or external assets fail.

## Verification

### Security and identity

- Bootstrap replay, expiry, crash recovery, and no-default-password tests.
- Password hashing, login throttling, session rotation/expiry, logout-all, suspension, password change, and recent-reauthentication tests.
- CSRF, Origin/Host, DNS-rebinding, loopback binding, WebSocket authorization, and cookie tests.
- Direct API bypass, cross-account identifier guessing, browser state leakage, and non-enumerating-error tests.
- Last-administrator, deny-overrides-grant, delegation, policy epoch, revocation-mid-operation, and unclassified-route CI tests.
- Tamper-evident audit chain, transactional audit failure, rotation, and redaction tests.
- Recovery with corrupt overlays and interrupted migration tests.

### Ownership and migration

- Complete store classification fixtures and Administrator ownership migration.
- Crash-resumable ledger, backup verification, rollback, stable-ID, path traversal, symlink/reparse, quota, and unsafe-downgrade tests.

### GitHub and Git

- Real-process credential-isolation spike for multiple `GH_CONFIG_DIR` roots on Windows.
- Ambient-token/config scrubbing and expected-host/identity binding tests.
- Concurrent login, logout/account-switch cancellation, device-code privacy, and shutdown ownership tests.
- Account-owned/shared checkout ACLs, serialized mutations, exact-SHA revalidation, and identity-change tests.

### Designer and overlays

- Stable object/property IDs, tombstones, deterministic composition, group priority, denial, quarantine, optimistic conflict, publication preview, and rollback tests.
- Server-side command authorization for every command and property.
- Personal/shared mode, preview-as-account, account-switch draft handling, responsive breakpoints, keyboard access, accessibility, and visual regression tests.

### Source Control UI

- Signed-out GitHub, connected/current, behind/update, ahead, diverged, dirty, repository mismatch, branch mismatch, detached, unavailable, and permission-denied states.
- Searchable repository behavior with large account lists.
- Desktop, tablet, and mobile visual verification with no horizontal overflow.
- Confirmation cancellation and stale-response generation tests.
- Full focused and repository regression suites, JavaScript syntax checks, `git diff --check`, live localhost health, and final in-app-browser inspection.

## Delivery Sequence

1. Threat-model fixtures, bootstrap, accounts, sessions, central policy, audit, fixed recovery shell.
2. Resource ownership classification and crash-safe legacy-data migration.
3. Account-scoped GitHub/Git isolation spike and service conversion.
4. Overlay persistence, policy-aware composition, publication, and durable revision recovery.
5. Complete the Designer shell and expand the application manifest with stable object/property IDs.
6. Create and validate the Codex and JSON_CODR UI-design skills.
7. Use the skill to implement the compact Source Control page and its Designer coverage.
8. Security, concurrency, responsive, live-browser, migration, and full regression verification.
9. Commit, push, update the open pull request, pull/verify the remote branch, restart the local application, and inspect the live page.

## Builder Decisions

The builder may choose exact table names, route names, inspector control layout, iconography, and responsive pixel breakpoints. Those choices must not change the policy semantics, protected invariants, account/GitHub isolation, overlay ordering, audit guarantees, migration recovery, or required user-visible identity distinctions.
