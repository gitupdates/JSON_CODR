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

Important checkpoint commits, oldest to newest:

> Autonomous coding security checkpoint: V1.0.18-alpha.17 adds exact one-use approvals, durable project context, capability discovery, broker-verified Qwen planning, iterative AgentRuntime execution, plan/step revision UI, isolated worktrees and commands, gated deployment adapters, and RT-01–RT-15 verification. UI Designer work still resumes at Task 4 below.

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
