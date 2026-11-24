# Unrestricted Profile Designer Design

## Intent

Extend the existing structured JSON_CODR Designer into an account-aware visual builder. Owner and Administrator accounts may compose unrestricted visual experiences, including custom HTML, CSS, JavaScript, assets, fonts, and component packages. Other accounts receive explicit role and capability-profile assignments.

Visual freedom must never make the running application unusable. Editing happens against drafts and isolated previews; the application serves only validated immutable published snapshots. Fixed recovery chrome, identity, authorization, and core command paths remain outside editable content.

## Selected architecture

The existing `DesignDocument`, component registry, reversible command engine, revision store, assets, references, capture adapters, and protected JSON_CODR manifest remain authoritative. This work extends those contracts rather than creating another page-builder state store.

Four records remain separate:

- `DesignProfile`: tokens, typography, assets, component variants, page trees, responsive layouts, and profile metadata.
- `CapabilityProfile`: a named set of allowed and denied actions with operational limits.
- `ProfileAssignment`: a subject, scope, profile, validity window, and revision.
- `ExecutableExtension`: quarantined HTML, CSS, JavaScript, or custom component package with provenance, digest, review state, and runtime capabilities.

Imports never carry active account assignments, credentials, grants, or automatically enabled scripts.

## Roles and policy

Base roles provide defaults: Owner, Administrator, Designer, Editor, Contributor, Reviewer, and Viewer. Capability profiles provide exceptions per account, project, site, page, or component.

Owner retains fixed recovery authority. Administrator receives unrestricted visual-building capabilities by default. Executable-code authority is distinct from ordinary design authority through `design.html.write`, `design.css.write`, `design.script.write`, `design.components.import`, `design.publish`, and `design.permissions.manage`.

Resolution order is:

1. fixed Owner recovery invariant;
2. explicit resource denial;
3. explicit resource grant;
4. project or site profile;
5. account capability profile;
6. role defaults;
7. default denial.

The server validates every mutation and publication. UI visibility is not authorization.

## Runtime-continuity contract

Designer changes cannot directly mutate the active application. The lifecycle is:

`editable draft -> isolated preview -> validation -> immutable revision -> atomic publication -> runtime snapshot`

Publication must fail without altering the current runtime snapshot when any of these conditions occurs:

- the document or component schema is invalid;
- a required core surface is missing or unreachable;
- navigation, command, permission, identity, recovery, or safe-mode invariants are violated;
- a component migration is unavailable;
- an executable extension lacks approval or requested runtime capabilities;
- the expected published revision is stale;
- asset, font, script, or component integrity checks fail.

Required core functions are represented as protected capabilities rather than protected visual positions. A skin may move or replace their presentation, but the application must retain at least one accessible route to workspace navigation, authentication/account identity, task execution, settings, recovery, and safe mode. A fixed recovery shell remains available even when every optional profile and extension is disabled.

Publication uses an atomic pointer swap to a fully materialized snapshot. Existing sessions keep the last known-good snapshot until the replacement is ready. A failed render activates the last known-good snapshot and records the failure; it never exposes a partially applied document.

## Visual builder

The builder provides a canvas, layers tree, component library, inspector, assets, profile manager, access inspector, history, and desktop/tablet/mobile preview. Authorized users can drag, reorder, group, resize, replace, hide, or delete editable nodes; paste or upload graphics; manage fonts and tokens; create reusable components; and save or clone profiles.

Every component definition declares a stable type and version, property schema, child and parent constraints, supported breakpoints, required capabilities, serializer, migration path, and fallback renderer. Unknown components become inert placeholders in the editor and cannot publish without a compatible approved runtime.

## Executable extensions

Owner and authorized Administrators may introduce arbitrary HTML, CSS, JavaScript, and local component packages. They enter quarantine and progress through receive, inventory, validate, preview, approve, and activate states.

Preview and runtime execution use a sandboxed origin without direct host DOM, credential, filesystem, or unrestricted network access. Extensions receive revocable, scoped host-API capabilities. CPU time, output, storage, network destinations, and message sizes are bounded. An emergency disable action can deactivate all extensions independently of profile rollback.

## Profiles and portability

Profiles support global, organization, account, project, site, page, and component-instance scopes. More-specific design values override broader design values, while authorization follows the deny-first policy above.

Exports contain design data, compatible assets, component manifests, extension source or packages, provenance, schema versions, and checksums. They exclude assignments, secrets, sessions, and active grants. Imports remain quarantined until validated for the destination environment.

## Concurrency, history, and recovery

Draft and publication writes use expected revision identifiers. Stale writes return a structured conflict and preserve both revisions. Published revisions are immutable. The system records author, scope, parent revision, component/runtime versions, validation report, and content digest.

Recovery supports restoring a prior snapshot, disabling extensions, resetting profiles without deleting content, and entering the fixed recovery shell from the CLI when the normal UI cannot render.

## Migration

Existing `json_codr_ui_v1` appearance state and `json_codr_workspace_layout_v1` layout state are imported as a personal design profile without modifying either legacy value. During rollout, the runtime can read the new published snapshot first and fall back to the existing appearance/layout controllers. The legacy write path is retired only after parity tests and a successful migration marker.

## Acceptance criteria

- A failed draft, preview, migration, extension, or publication cannot replace the active snapshot.
- Core application functions remain reachable after moving, replacing, hiding, or deleting editable elements.
- Owner recovery and safe mode work with all profiles and extensions disabled.
- Permission enforcement is identical through UI, API, background work, and imported profiles.
- Profile exports cannot grant access or execute imported scripts automatically.
- Existing appearance presets and workspace layouts migrate without visible regression.
- Desktop, tablet, and mobile snapshots remain operable and keyboard accessible.
