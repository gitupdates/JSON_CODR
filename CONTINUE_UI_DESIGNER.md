# UI Designer emergency restore and continuation

Updated: 2026-11-19 (America/Chicago)

Integration base: `alpha/hybrid-zero-layer` at `a3dd575`. The UI Designer checkpoints were replayed onto that base without replaying the older guided-agent commits that the Hybrid runtime supersedes.

This file is the compact recovery record for continuing the Gamma UI Designer work from another machine. The authoritative requirements and task details are already committed in:

- `docs/superpowers/specs/2026-11-18-ui-designer-design.md`
- `docs/superpowers/plans/2026-11-18-ui-designer-implementation.md`

## Quick restore on another machine

For a new clone in PowerShell:

```powershell
git clone https://github.com/gitupdates/JSON_CODR.git
cd JSON_CODR
git switch --track origin/codex/hybrid-zero-layer-ui-designer
git status
git log -1 --oneline
```

For an existing clone:

```powershell
git fetch origin
git switch codex/hybrid-zero-layer-ui-designer
git pull --ff-only
git status
git log -1 --oneline
```

Expected branch: `codex/hybrid-zero-layer-ui-designer`.

Use Python 3.14 for the Hybrid web host because Hybrid uses the standard-library `uuid7`. Keep Python 3.12 as the explicitly configured optional-hardware sidecar runtime.

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m pip install -r requirements.txt
$env:JSON_CODR_COMPATIBLE_PYTHON = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
```

Verify the restored checkpoint:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m unittest test_designer_contracts.py test_designer_store.py test_designer_components.py test_settings.py test_inference_sidecar.py -v
```

The 2026-11-19 integration checkpoint passes all 55 focused Designer/settings/sidecar tests. The full repository discovery run completed 691 tests with 2 failures and 6 errors in pre-existing Windows environment-sensitive tests (short-path versus long-path comparisons, PowerShell helper execution, and a Node subprocess crash); these are outside the Designer integration surface.

## Current progress

Completed on the Hybrid integration branch:

1. Scene contracts, Designer settings, appearance migration, canonical digesting, immutable nested scene data, responsive overrides, and bounded graph validation.
2. Atomic project store, immutable parent-linked revisions, optimistic digest conflicts, recoverable drafts, restore, duplication, deletion confirmation, and managed-root confinement.
3. Data-only registry for all 24 built-in component types, Blank/Landing Page/Dashboard/Form templates, NOC Light defaults, and the versioned 16-region protected JSON_CODR manifest.
4. Python 3.14 host execution can explicitly select a Python 3.11/3.12 optional-hardware sidecar through `JSON_CODR_COMPATIBLE_PYTHON`.
5. Serializable browser commands, Python-compatible canonical digests, reversible scene edits, selection transforms, snapping, undo/redo, and protected-node checks.
6. Managed image/SVG/font imports, bounded capture envelopes, authorized Playwright capture, sanitized reference archives/previews, screenshot asset storage, and reference provenance.

Important checkpoint commits, oldest to newest:

| Commit | Purpose |
|---|---|
| `d792fab` | UI Designer design specification |
| `5dc0256` | Sanitized UI reference capture design |
| `4b2a753` | Implementation plan |
| `c6ed1e6` | Playwright-only first-release capture policy |
| `08adaa3` | Scene contracts and Hybrid-compatible Designer settings |
| `f01f1d8` | Lossless CSS extraction requirements |
| `b1701d8` | Atomic project history |
| `fb7aa07` | Components, templates, and protected manifest |
| `00e0515` | Undoable browser scene commands |
| `aef05d6` | Chat paperclip opens the multi-file chooser |
| `66a5970` | Managed assets and sanitized UI reference imports |

## Architecture resolution

The selected design is one structured, versioned scene model shared by JSON_CODR customization and user projects, with stack/grid as the responsive default and bounded freeform positioning inside freeform containers. Direct live-DOM editing was rejected because it can break application behavior and upgrades; separate customization and page-builder systems were rejected because they duplicate the editor, persistence, and export surface. JSON_CODR remains protected through an overlay and locked capabilities.

## Task 5 deliverables

Task 5, **Managed assets and sanitized Playwright reference capture/import**, is implemented. Its required files are:

- `web_app/designer/assets.py`
- `web_app/designer/references.py`
- `web_app/designer/capture_adapters.py`
- `web/designer_capture.js`
- `tools/playwright_ui_capture.mjs`
- `tools/make_ui_reference_archive.py`
- `docs/user/ui-reference-capture.md`
- `test_designer_assets.py`
- `test_designer_references.py`

Task 5 keeps imported references inert and sanitized. It rejects prohibited capture fields, validates generated asset paths and checksums, bounds image/archive/resource sizes, and requires authorization/license provenance. It does not install Playwright or browser binaries; the capture adapter reports when the optional runtime is unavailable.

Task 4 added:

- `web/designer_model.js`
- `web/designer_commands.js`
- `test_designer_commands.py`

Its focused tests cover every serializable command and inverse, conflicts, protected nodes, snapping and selection transforms, bounded freeform geometry, breakpoint inheritance, and history behavior.

## Resume point

Start with **Task 6: Lossless CSS parser, import resolver, and cycle bundles** in the implementation plan. Task 5 verification passed:

```powershell
python -m unittest test_designer_assets.py test_designer_references.py test_designer_contracts.py test_designer_store.py test_designer_components.py test_designer_commands.py -v
```

The focused command ran 52 tests successfully. `node --check` passed for both capture JavaScript files, Python compilation passed for the new modules/tools, and `git diff --check` was clean.

## Remaining task sequence

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
6. Push `codex/hybrid-zero-layer-ui-designer` to `origin` immediately.
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
git switch codex/hybrid-zero-layer-ui-designer
git pull --ff-only
git status
```

Only the last pushed commit is guaranteed to be recoverable from GitHub. Review any local changes before discarding or overwriting them. Resume from the first incomplete task above, rerun its RED/green tests, then commit and push the next checkpoint.
