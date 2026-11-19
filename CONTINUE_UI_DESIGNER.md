# UI Designer emergency restore and continuation

Updated: 2026-11-18 (America/Chicago)

This file is the compact recovery record for continuing the Gamma UI Designer work from another machine. The authoritative requirements and task details are already committed in:

- `docs/superpowers/specs/2026-11-18-ui-designer-design.md`
- `docs/superpowers/plans/2026-11-18-ui-designer-implementation.md`

## Quick restore on another machine

For a new clone in PowerShell:

```powershell
git clone https://github.com/gitupdates/JSON_CODR.git
cd JSON_CODR
git switch --track origin/codex/alpha.12-guided-task-flow
git status
git log -1 --oneline
```

For an existing clone:

```powershell
git fetch origin
git switch codex/alpha.12-guided-task-flow
git pull --ff-only
git status
git log -1 --oneline
```

Expected branch: `codex/alpha.12-guided-task-flow`.

Install the project dependencies with a compatible Python 3.12 environment. Python 3.14 may run the web host and focused pure-Python tests, but optional hardware runtime environments require Python 3.11 or 3.12.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:JSON_CODR_COMPATIBLE_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe)
```

Verify the restored checkpoint:

```powershell
& .\.venv\Scripts\python.exe -m unittest test_designer_contracts.py test_designer_store.py test_designer_components.py -v
& .\.venv\Scripts\python.exe -m unittest test_guided_task_e2e.py -v
```

## Current progress

Completed and pushed:

1. Scene contracts, Designer settings, appearance migration, canonical digesting, immutable nested scene data, responsive overrides, and bounded graph validation.
2. Atomic project store, immutable parent-linked revisions, optimistic digest conflicts, recoverable drafts, restore, duplication, deletion confirmation, and managed-root confinement.
3. Data-only registry for all 24 built-in component types, Blank/Landing Page/Dashboard/Form templates, NOC Light defaults, and the versioned 16-region protected JSON_CODR manifest.
4. Existing guided task flow retains persistent SQLite task/plan/event state; `test_guided_task_e2e.py` verifies a reviewed task survives restart and produces verified delivery.

Important checkpoint commits, oldest to newest:

| Commit | Purpose |
|---|---|
| `b73d8c5` | UI Designer design specification |
| `ba7c1dd` | Sanitized UI reference capture design |
| `cb83788` | Implementation plan |
| `9b62ff0` | Playwright-only first-release capture policy |
| `2156d39` | Scene contracts and settings |
| `f36f913` | Lossless CSS extraction requirements |
| `b3dda90` | Atomic project history |
| `b36d74c` | Components, templates, and protected manifest |

## Resume point

Start with **Task 4: Serializable command engine and browser document model** in the implementation plan. Its required files are:

- `web/designer_model.js`
- `web/designer_commands.js`
- `test_designer_commands.py`

Task 4 workflow:

1. Write Node-backed failing tests for every serializable command and inverse.
2. Confirm the JavaScript modules are absent (RED).
3. Implement a pure deterministic model with no DOM or network access.
4. Require the expected document digest and return structured conflicts.
5. Run focused tests, commit, and push before starting Task 5.

## Remaining task sequence

4. Serializable command engine and browser document model.
5. Managed assets and sanitized Playwright reference capture/import.
6. Lossless CSS parser, recursive `@import` resolver, Tarjan SCC cycle bundles, exact comment preservation, and deterministic serialization.
7. Designer API surface and conflict-safe uploads.
8. Sandboxed renderer, validation, and static export.
9. Settings enablement and Designer application shell.
10. Canvas manipulation, inspector, and reference drafting.
11. Protected JSON_CODR overlay, rebase, and safe mode.
12. End-to-end verification, documentation, and release integration.

For each task, follow the same recoverable cycle:

1. Add the failing tests first and record the expected failure.
2. Implement only that task's interfaces.
3. Run its focused tests plus affected earlier Designer tests.
4. Run `git diff --check` and inspect `git status`.
5. Commit a small task-specific checkpoint.
6. Push `codex/alpha.12-guided-task-flow` to `origin` immediately.
7. Update this file if the resume point or a major ruling changes.

## Requirements that must not be lost

- Playwright is the only first-release browser automation adapter; Puppeteer is future compatibility only.
- Imported UI references are inert and sanitized. Do not persist scripts, cookies, headers, storage, form values, authentication state, API bodies, or executable behavior.
- Capture is bounded and requires authorization/license provenance.
- CSS `@import` parsing is token-based and preserves URL form, query/fragment, layer, supports, media, and source location.
- CSS resolver limits are depth 32, 512 stylesheets, 5 MiB per stylesheet, and 64 MiB total.
- Cyclic CSS imports use deterministic Tarjan SCC bundles named `bundle_scc_NNN.css`.
- Comments are first-class: preserve exact raw text, whitespace, position, trailing/EOF/comment-only/license/directive comments, and unchanged parse-to-serialize bytes.
- NOC Light is the default; JSON_CODR Classic-style header collapsing remains available.
- The end user can later change themes, component mappings, layout, size, image, typography, and other standard UI properties.
- JSON_CODR itself uses a protected overlay. Essential navigation, Settings, Designer exit, recovery, approvals, and terminal behavior may not be removed or rebound.
- IBM Plex must not be reintroduced; system stacks, OpenDyslexic, and explicitly imported open-source web fonts are allowed.
- Use generated identifiers and managed data roots; never accept caller-supplied filesystem paths for project APIs.
- Preserve unrelated user work and do not use destructive Git reset/checkout operations.

## If a task is interrupted

On the next machine, first run:

```powershell
git fetch origin
git switch codex/alpha.12-guided-task-flow
git pull --ff-only
git status
```

Only the last pushed commit is guaranteed to be recoverable from GitHub. Review any local changes before discarding or overwriting them. Resume from the first incomplete task above, rerun its RED/green tests, then commit and push the next checkpoint.
