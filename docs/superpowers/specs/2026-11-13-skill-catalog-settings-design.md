# Skill Catalog and Settings Design

## Intent

Give JSON_CODR one persistent, model-independent catalog for installed skills. A user can understand what each skill does before selecting it, export its documentation, minimize or reopen the catalog, and manage this behavior from Settings. Additional skills are discovered only when the user explicitly scans an approved folder.

## Goals

- List only skills already installed in JSON_CODR on initial load.
- Treat converted Claude, Codex, and generic skills as JSON_CODR skills usable with any selected LLM through the existing prompt-context mechanism.
- Show details for a selected skill: purpose, intended use, abilities, command structure and syntax, examples, source format, enabled state, and raw/converted instructions.
- Export an individual skill's documentation on demand as a downloadable Markdown file.
- Make the catalog collapsible and persist its open/closed state.
- Add a Settings surface backed by one extensible system configuration record. Initially it stores catalog visibility and approved skill scan locations; later settings can add filesystem or integration configuration without a second storage mechanism.
- Let the user explicitly scan a chosen folder, review detected compatible packs, and install chosen results.
- If an explicit scan finds no compatible skills, offer—but never automatically run—a scan of known Claude, Codex, and JSON_CODR skill locations.

## Non-goals

- No automatic whole-drive scanning.
- No background watching of folders.
- No remote marketplace or internet discovery.
- No silent installation, conversion, or modification of discovered skills.
- No model-specific copies of an installed JSON_CODR skill.
- No direct execution privileges added to skills; capability and CLI safety rules remain unchanged.

## Constraints

- Existing installed packs and per-session selections must continue to work without migration work by the user.
- Settings are local system configuration, not chat-session data.
- Scan paths must be explicit directories, resolved locally, and rejected when missing or not directories.
- Discovery must be bounded and ignore unsafe archive paths, unsupported files, and oversized packs using the existing converter limits.
- A known-location scan requires a separate user confirmation after an empty explicit scan.
- The UI remains local-first and works without a chosen or running LLM.
- Known-location discovery is bounded to user-level provider locations for the host OS. On Windows these begin with `%USERPROFILE%\.claude`, `%USERPROFILE%\.codex\skills`, and JSON_CODR's configured data root; equivalent home-directory locations are used on other hosts. The scanner inspects only recognized skill-pack layouts and archives within a fixed depth and entry limit.

## Approaches Considered

### Explicit folders with preview and optional fallback — selected

Store approved folder paths in Settings. A scan returns a non-mutating discovery preview. The user installs selected results. When the preview is empty, the UI offers a separately confirmed scan of known application locations. This is transparent, repeatable, and avoids unrelated filesystem access.

### Browser folder import

Upload selected directory contents through the browser. This is portable but loses stable source paths and makes later rescans awkward.

### Automatic known-location discovery

Search common provider directories immediately. This is convenient but less predictable and violates the requirement that broader discovery be requested only after an explicit scan is empty.

## Data Design

Add a versioned JSON settings record under the existing JSON_CODR data root. The initial schema contains:

- `version`
- `ui.skill_catalog_open`
- `skill_scan.approved_directories`

Unknown future fields are preserved when settings are updated so later filesystem and integration configuration can share this record. Writes use a temporary file and atomic replacement.

Installed skill records gain optional structured documentation fields derived during conversion:

- `intent`
- `abilities`
- `command_syntax`
- `examples`

Legacy records without these fields remain valid. Their detail view derives a useful fallback from the existing description and converted instructions.

## Service and API Design

Keep filesystem and documentation behavior in services; HTTP handlers only validate, call services, and map errors.

- `GET /api/settings` returns the system settings record.
- `PATCH /api/settings` updates supported settings and persists them.
- `POST /api/skills/scan` accepts one explicit directory, records it as approved, and returns compatible discoveries without installing them.
- `POST /api/skills/scan-known` performs the fallback scan only after an explicit user action.
- `POST /api/skills/install-discovery` installs one reviewed discovery through the existing conversion and duplicate-prevention path.
- `GET /api/skills/{pack_id}/{skill_id}/documentation.md` returns generated Markdown documentation as an attachment.

An empty explicit scan returns a short-lived, single-purpose fallback token. The server requires this token for `scan-known`, so direct API callers cannot bypass the confirmation sequence. Tokens and discovery previews are process-local, bounded in number, expire after ten minutes, and are invalid after restart or rescan.

Discovery results use opaque server-generated IDs tied to resolved paths for the current process. The install endpoint resolves the source again and verifies its digest against the preview; changed or missing sources require a new scan. The browser never supplies an arbitrary unreviewed install path.

The Markdown export includes identity, source, intent, abilities, syntax, examples, compatibility guidance, and the converted instructions. Documentation is generated on demand and does not create an unmanaged duplicate file on disk.

## UI Design

Add a `Skills` top-bar toggle alongside CLI and Context. It opens a dedicated collapsible catalog panel so the list is not buried inside attachment context. The panel contains:

- installed pack and skill list;
- selected/enabled indicators;
- a detail region opened by `Details`;
- select/deselect, edit, enable/disable, remove-pack, and documentation download actions;
- `Scan folder` and discovery preview/install controls;
- the conditional `Scan known locations` offer shown only after an empty explicit scan.

Add a `Settings` top-bar action opening a settings panel. The initial sections are UI state and Skill Discovery. Closing or reopening the Skills panel updates Settings through the API; local browser storage may be used only as a temporary startup hint, with persisted Settings authoritative.

An explicit directory is added to approved locations only after it resolves to a valid directory and a scan completes, including a valid scan with zero results. Settings provides `Rescan` and `Remove` for every approved location. Approval permits only user-triggered rescans; it never starts background access.

The existing compact skill controls inside Context are replaced by a link or button that opens the Skills panel, avoiding two competing catalogs.

## Cross-model Behavior

Installed skills remain provider-neutral prompt context. Any locally selected LLM receives the same enabled and selected converted instructions. The detail view clearly distinguishes declarative instructions from executable capabilities: a skill may describe commands or tools, but the current runtime must actually provide and authorize them.

`enabled` remains a global property of an installed skill. `selected` remains a per-chat-session reference to an enabled skill. Disabling a skill prevents new selection and removes it from effective prompt context without creating provider-specific state.

New conversions may store extracted structured documentation. Existing records are not migrated or rewritten: details and exports derive missing fields dynamically from their description and converted instructions. A legacy record changes only when the user explicitly edits or reinstalls it.

## Error and Empty States

- Missing or invalid directory: explain that no scan ran and preserve prior approved paths.
- No compatible skills: show the optional known-location scan action.
- Duplicate discovery: label it already installed and disable installation.
- Partial scan failures: return usable discoveries plus per-item warnings.
- Documentation generation failure: keep the catalog usable and show a scoped error.

## Verification

- Service tests cover settings persistence, preservation of unknown fields, explicit scanning, empty results, bounded known-location fallback, duplicate labeling, reviewed installation, and Markdown output.
- API tests cover validation, non-mutating previews, installation, and documentation download headers/content.
- Browser verification covers minimizing and reopening through Settings, skill details, export, an empty explicit scan followed by the optional known-location prompt, and persistence after reload.

## Builder Decisions

The builder may choose exact responsive layout, labels, and extraction heuristics for structured documentation, provided raw converted instructions remain available and the required safety/confirmation behavior is preserved.
