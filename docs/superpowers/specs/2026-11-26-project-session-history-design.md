# Project Session History Design

## Intent

JSON_CODR must separate the transient Workspace interaction from durable project history. Opening Workspace starts a clean live session and displays only messages created or explicitly restored into that session. A user can save the live session to a project, continue working, start another clean session, and later restore an immutable saved snapshot as a new live working copy.

## Goals

- Stop reopening the last browser session automatically on page load.
- Display only the current live session in the Workspace response timeline.
- Add explicit **New Session**, **Save Session to Project**, and **Restore Session** controls.
- Add a nested **Projects & Sessions** section under Workspace that shows the selected project plus the current unassigned or project-bound live session.
- Allow Workspace to run before a project is selected; keep current actions and discussion in an unassigned page-scoped Session container until the user backs it up, saves it to a project, or clears it.
- Save prompts, responses, model routing, public reasoning, references, attachments, selected skills, and project identity together.
- Preserve saved snapshots as immutable project history while allowing the live session to continue.
- Compact saved conversations into a bounded, keyword-searchable Previous Session History record.
- Make saved sessions and their compacted history visible from Context & Files.
- Restore by creating a new live copy so later edits cannot mutate the saved snapshot.
- Automatically retrieve relevant Previous Session History for new prompts in the same project and identify the source records supplied to the model.
- Give every saved feature, fix, enhancement, code/file change, and investigation deterministic searchable identifiers plus optional user keywords.
- Keep single-model Run available when Ollama has at least one downloaded unquarantined model, including after compatibility-state reload.
- Make Ask All Available Models use the current live session and authenticated mutation/CSRF transport without 403 failures.

## Non-goals

- Do not silently save every transient session as project history.
- Do not inject an entire historical transcript into every prompt.
- Do not delete legacy session directories during migration.
- Do not depend on a vector database; scoped SQLite/FTS5 remains authoritative.
- Do not restore terminal processes, pending approvals, or in-flight tasks.

## Selected approach

Use immutable project snapshots plus copied live sessions. This was selected over reopening a mutable session ID, which would mix new work into saved evidence, and over ZIP-only export/import, which would not support searchable Context & Files history.

Saving leaves the live session active. Starting a new session is a separate explicit action. Restoring a snapshot creates a fresh session whose initial messages, attachments, references, and skill selections are copied from the snapshot.

## Storage model

Extend the workspace data root with `project-sessions/<sha256-project-key>/sessions/<snapshot-id>/`. The filesystem key is derived from the registered project ID because canonical IDs contain `:` and are not valid Windows directory names. Each saved snapshot contains:

- a schema-versioned `snapshot.json` manifest;
- the source session metadata and messages;
- copied original and extracted attachments;
- a bounded `previous-session-history.md` summary;
- deterministic keywords derived from prompts, responses, attachment names, references, and model identities.

Project IDs are derived from the registered project root rather than accepting arbitrary filesystem paths. Every snapshot stores the authenticated owner ID and registered project ID. Live sessions gain optional owner/project identity so restored references remain bound to the same authority. Snapshot and session identifiers use validated server-generated IDs. Files are copied through the existing workspace boundary checks, written into a staging directory, and atomically promoted. Snapshot manifests are immutable after promotion.

Save and restore take a per-session lock shared with conversation and attachment mutations. The saved manifest and copied trees are digest-validated before promotion, abandoned staging directories are removed, and a failed restore deletes the partially allocated live session. Original/extracted attachments and session artifacts are copied; project-file references resolve through the registered project associated with the session rather than the JSON_CODR source repository.

The compacted summary is also accepted into the existing owner- and project-scoped collective memory store when memory is enabled. It uses kind `previous_session_history`, nonempty snapshot source references, `retain_details=false`, a deterministic idempotency key, and a hard 65,536-character ceiling. Full transcript indexing is not performed; it would require both explicit per-save opt-in and the existing system detailed-retention setting. The snapshot remains the durable source of truth; FTS memory is a searchable projection that can be rebuilt. Secret-content policy remains enforced. If collective memory is disabled or rejects content, saving the snapshot still succeeds and reports that indexing was skipped.

## API

- `POST /api/sessions` accepts a validated registered project ID and creates a clean owner/project-bound live session, so relevant history is available to the first prompt.
- `POST /api/projects/resolve` registers/resolves a project root and returns its server-derived project ID.
- `POST /api/projects/{project_id}/sessions` saves the current session with title, change type, and optional keywords, returning snapshot metadata and indexing status.
- `GET /api/projects/{project_id}/sessions?query=...` lists owner-scoped saved snapshots without full transcripts and supports keyword search.
- `POST /api/projects/{project_id}/sessions/{snapshot_id}/restore` creates a new owner/project-bound live copy.
- `GET /api/projects/{project_id}/sessions/{snapshot_id}` returns snapshot metadata and compacted history for Context & Files.

Mutating routes use the existing identity and CSRF boundary and are registered as `session.write` mutations. A shared authenticated-principal helper accepts browser-session cookies and CLI/service bearer credentials; mutations require `session.write` and browser CSRF, while owner-scoped GET routes authenticate without CSRF. Project identity is resolved server-side through the project registry. Every list/get/save/restore checks the authenticated owner and project ID. Save and restore reject unknown or differently owned sessions, invalid identifiers, reparse-point escapes, partial snapshots, and cross-project access.

## Browser behavior

The browser no longer treats `json_codr_session` as durable history. A page load creates a clean page-scoped session and renders the empty state. When a project is already selected, the project is resolved before creating the session so first-prompt history is available. When no project is selected, the session remains an authenticated unassigned live session until the user selects or creates a project for saving, downloads a backup, or clears it. The current session ID may exist only for the lifetime of the loaded page and is exposed to independent clients such as Ask All Available Models through a page-scoped live-session provider.

The Workspace toolbar exposes:

- **New Session** — creates a clean session after warning only when there is unsaved content;
- **Save Session to Project** — collects a title, change type, and optional keywords, saves an immutable snapshot, and keeps the current interaction visible;
- **Restore Session** — opens a project-scoped picker and replaces the live timeline with a newly created copy.
- **Backup Session** — exports the current unassigned or project-bound session without silently promoting it to project history;
- **Archive to Context & Files** — saves the session with title/change type/keywords, refreshes Previous Session History, and starts a clean live session so archived responses leave the main chat while remaining searchable and restorable.

Workspace gains a nested **Projects & Sessions** section. Its Projects area resolves or creates the current registered-project selection from a workspace root and exposes that project's saved history. Its Sessions area always shows the current live container, its assignment state, unsaved activity/message counts, and actions to back up, save/archive to a project, restore, or clear/reset. Context & Files gains a searchable **Previous session history** section listing saved snapshots, change type, identifiers, keywords, date, model summary, and indexing state. Restored attachments appear through the existing attachment list. The timeline never merges multiple saved sessions, and archived content is shown in history rather than rehydrated into the active chat unless explicitly restored.

## Compaction and retrieval

Compaction is deterministic and bounded. It retains the session title, dates, user objectives, assistant outcomes, model identities, attachment/reference labels, warnings, and the final status of each interaction. It excludes private reasoning and raw binary data.

Keywords are normalized, deduplicated, length-bounded, and stored in the snapshot manifest and summary front matter. Every snapshot has identifiers for `snapshot`, `project`, `session`, `change-type`, and title slug; code-bearing sessions also add `file`, `component`, `model`, `task`, and reference identifiers when available. Optional user keywords are merged under the same bounds.

Before direct-model, agent-workspace, and compatibility API prompts are assembled, JSON_CODR queries active `previous_session_history` FTS records using safe normalized terms from the current prompt, authenticated owner, and registered project. The context assembler receives only a bounded set of relevant summaries under an untrusted-reference-data marker, includes source refs such as `previous-session:<snapshot-id>`, tells the model to use history only when relevant and to cite those refs, and always gives the current request precedence. The exact supplied records are also emitted as structured `previous_session` references in `ContextBuildResult`, inference/task results, and persisted conversation messages, so provenance does not depend on model-written citations. Invalid FTS syntax yields no history rather than failing the prompt. When memory is disabled, prompt execution continues without historical retrieval.

## Live prompt regressions

Ollama inventory returns artifact digests as bare 64-hex values, while JSON_CODR stores canonical digest identity as `sha256:<hex>`. The compatibility layer accepts either transport spelling, canonicalizes both to the prefixed form, and reads existing bare-digest state without treating the whole state file as invalid. Untested installed models remain manually probeable, digest-matched compatible models remain runnable, and only explicit blocking evidence stays unavailable. Thus a fresh session leaves Run enabled whenever an eligible downloaded candidate exists.

The all-model browser client obtains or creates the page-scoped live session instead of reading `json_codr_session`. Its start and cancel POSTs use `JSONCodrHttpIdentity.mutationHeaders`; read-only polling/export behavior is unchanged. A 401/403 response reports server detail and re-enables the control.

## Compatibility and migration

Existing session directories remain readable for exports and API compatibility. The browser simply stops reopening their IDs automatically. Existing conversation export endpoints continue to operate on the current live session. No legacy session is automatically promoted into project history.

## Verification

- A fresh browser load has a new session ID and an empty timeline.
- With no selected project, Run remains available for eligible models and the current actions/discussion appear in an unassigned Sessions container until backup, save/archive, or clear/reset.
- Projects & Sessions is visible directly under Workspace and switching or creating a project never silently merges sessions.
- The new session is project-bound before its first prompt, and first-prompt history retrieval works.
- Reloading does not render messages from an earlier unsaved session.
- Saving preserves the live timeline and creates one complete immutable snapshot.
- Context & Files lists the saved snapshot and its compacted searchable history.
- Archive to Context & Files removes archived responses from the active chat by starting a clean live session while retaining keyword-searchable history and restore capability.
- Restoring creates a different live session ID with equivalent messages and attachments.
- Restored artifacts and project-file references remain resolvable within the registered project.
- Continued work after restore does not modify the saved snapshot.
- Cross-project restore, traversal, reparse points, malformed IDs, CSRF failure, and interrupted writes fail closed.
- Memory-disabled and memory-policy-rejected saves retain the snapshot and expose indexing status.
- A new prompt retrieves only relevant, active, same-owner/same-project Previous Session History records and exposes their source refs to the model.
- The exact supplied previous-session refs are present in structured response/message metadata even when model text contains no citation.
- Feature/fix/enhancement/file/component/model/task identifiers and user keywords find the expected saved record quickly.
- Bare and prefixed Ollama digests load as the same canonical identity; eligible downloaded models keep single-model Run enabled.
- Ask All Available Models starts and cancels through authenticated CSRF-safe requests using the current page session, without a 403.
- Existing chat, attachment, export, model-run, and project-agent behavior remains intact.
