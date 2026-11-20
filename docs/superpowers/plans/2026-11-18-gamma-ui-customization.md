# Gamma UI Customization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NOC Light the default JSON_CODR Gamma interface while preserving collapsible navigation and allowing users and developers to replace visual component variants later.

**Architecture:** Add a testable UMD-style catalog/state controller beside the existing vanilla frontend, then apply validated state through semantic `data-ui-*` attributes and CSS custom properties. A Settings-based Appearance editor edits a draft, previews it immediately, and saves one versioned local state object; existing application IDs, event wiring, workspace layout, server APIs, and navigation persistence remain authoritative.

**Tech Stack:** Vanilla HTML/CSS/JavaScript, Node.js built-in `assert` invoked from Python `unittest`, FastAPI static files, browser `localStorage`.

**Spec:** `docs/superpowers/specs/2026-11-18-gamma-ui-customization-design.md`

## Global Constraints

- Work only on `gamma/ui-customization`; do not modify the Alpha checkout.
- Use the existing Python installations and do not repair or change runtime discovery.
- Keep the frontend dependency-free and compatible with its current script-tag loading model.
- Preserve all stable element IDs, API contracts, task flows, keyboard behavior, ARIA relationships, and responsive workspace behavior.
- Default to `noc-light`, fixed light mode, compact density, IBM Plex preference with system fallback, expanded labeled navigation, flat panels, compact controls, and segmented tabs.
- Persist appearance under `json_codr_ui_v1`; valid versioned state wins over `json_codr_theme`.
- Do not import NOCWatch application logic, maps, data, vendor libraries, branding, or unlicensed font binaries.
- Imported binary assets are limited to the approved OpenDyslexic files and license unless an authoritative IBM Plex license is added with the binaries.
- User-authored CSS and remote themes remain unsupported.

## Review Focus

- Corrupt, wrong-schema, or partially valid `json_codr_ui_v1` data must recover to NOC Light while retaining only allowlisted overrides; Task 1 tests this normalization.
- A fixed-color preset must retain but not apply the user's adaptive mode, then restore it when switching to an adaptive preset; Task 1 tests this mode lifecycle.
- OpenDyslexic plus compact density must normalize to comfortable density, and Accessible Read must never become compact; Task 1 tests both combinations.
- Canceling an Appearance preview must restore the exact pre-edit state without writing storage; Task 4 tests draft/save/cancel behavior.
- Collapsed NOC Light navigation must preserve the active destination, remain keyboard operable, and restore its persisted state after reload; Task 5 tests the markup/runtime contracts and performs browser verification.

---

## File structure

- Create `web/ui_catalog.js`: immutable catalog, preset/variant allowlists, default state, migration, and state normalization.
- Create `web/ui_customization.js`: draft controller, DOM attribute application, Appearance editor binding, save/cancel/reset, and live-region updates.
- Create `web/gamma.css`: NOC Light default tokens, all approved preset tokens, component-family variants, responsive rules, and accessibility fallbacks.
- Create `web/fonts/fonts.css`: approved local font faces and fallback stacks.
- Create `web/fonts/opendyslexic-400.woff2`, `web/fonts/opendyslexic-700.woff2`, and `web/fonts/OpenDyslexic-OFL.txt`: approved archive assets.
- Create `web/fonts/THIRD_PARTY_NOTICES.md`: archive provenance and shipped font notices.
- Create `test_ui_customization.py`: Node-backed catalog/controller unit tests that do not import the FastAPI application.
- Modify `web/index.html`: synchronous first-paint bootstrap, Gamma stylesheet/scripts, and Appearance editor markup.
- Modify `web/app.js`: bridge existing settings/theme/navigation state to the new customization controller without moving unrelated behavior.
- Modify `web/app.css`: replace conflicting global token defaults with semantic compatibility aliases and retain existing layout rules.
- Modify `test_web_static.py`: static integration, accessibility, asset, and load-order contracts.

### Task 1: Catalog and state normalization

**Files:**
- Create: `web/ui_catalog.js`
- Create: `test_ui_customization.py`

**Interfaces:**
- Produces: `window.JSONCodrUICatalog` and CommonJS export with `STORAGE_KEY`, `LEGACY_THEME_KEY`, `DEFAULT_STATE`, `PRESETS`, `COMPONENTS`, `normalizeState(candidate, legacyMode)`, and `effectiveState(state, systemDark)`.
- `normalizeState` returns a fresh schema-1 state with keys `schema`, `preset`, `mode`, `density`, `typography`, and `components`.
- `effectiveState` returns the normalized state plus `effectiveMode` without overwriting the retained adaptive `mode` for fixed presets.

- [ ] **Step 1: Write failing catalog tests**

Add `GammaUICustomizationTests` cases that invoke Node and assert:

```js
const ui = require(modulePath);
assert.strictEqual(ui.DEFAULT_STATE.preset, "noc-light");
assert.strictEqual(ui.normalizeState(null, "dark").preset, "noc-light");
assert.strictEqual(ui.normalizeState({schema: 99, preset: "terminal-focus"}, "system").preset, "noc-light");
assert.deepStrictEqual(ui.normalizeState({schema: 1, preset: "noc-light", components: {navigation: "rail", panels: "unknown", surprise: "x"}}).components, {navigation: "rail"});
assert.strictEqual(ui.effectiveState(ui.normalizeState({schema: 1, preset: "noc-light", mode: "dark"}), false).effectiveMode, "light");
assert.strictEqual(ui.normalizeState({schema: 1, preset: "accessible-read", density: "compact"}).density, "comfortable");
assert.strictEqual(ui.normalizeState({schema: 1, preset: "gamma-operations", typography: "opendyslexic", density: "compact"}).density, "comfortable");
```

Also iterate every preset and assert that it supplies one allowed variant for each required component family.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest -v test_ui_customization`

Expected: FAIL because `web/ui_catalog.js` does not exist.

- [ ] **Step 3: Implement `web/ui_catalog.js`**

Use the existing `workspace_layout.js` UMD pattern. Encode the exact preset matrix and variant inventory from the spec, freeze exported catalog objects, normalize only allowlisted keys/values, clone all returned state, and keep fixed-preset mode override inside `effectiveState`.

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m unittest -v test_ui_customization`

Expected: all Task 1 tests PASS under the existing Python because the tests execute JavaScript through Node and do not import `web_app.app`.

- [ ] **Step 5: Commit**

```powershell
git add web/ui_catalog.js test_ui_customization.py
git commit -m "feat(ui): add gamma appearance catalog"
```

### Task 2: Draft controller, migration, and persistence

**Files:**
- Create: `web/ui_customization.js`
- Modify: `test_ui_customization.py`

**Interfaces:**
- Consumes: `JSONCodrUICatalog.normalizeState`, `effectiveState`, `STORAGE_KEY`, and `LEGACY_THEME_KEY` from Task 1.
- Produces: `window.createUICustomizationController(options)` and CommonJS export.
- Options: `{catalog, load, save, removeLegacy, apply, announce, systemDark}`; storage and DOM effects are injected for deterministic tests.
- Controller methods: `getState()`, `getDraft()`, `begin()`, `selectPreset(id)`, `setMode(mode)`, `setDensity(density)`, `setTypography(typography)`, `setComponent(family, variant)`, `resetComponent(family)`, `resetPreset()`, `save()`, and `cancel()`.

- [ ] **Step 1: Write failing controller tests**

Cover these exact behaviors with injected arrays/spies:

- versioned state wins over a conflicting legacy theme;
- missing versioned state is seeded in memory from valid legacy `light|dark|system` without writing;
- `save()` writes `json_codr_ui_v1`, removes `json_codr_theme`, and announces a saved state;
- `begin()` followed by draft mutations and `cancel()` reapplies the exact snapshot without writing;
- preset selection removes overrides and retains the adaptive mode;
- setting NOC Light navigation to `rail` survives save/load;
- invalid component family/variant calls leave the draft unchanged.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest -v test_ui_customization`

Expected: FAIL because `createUICustomizationController` is unavailable.

- [ ] **Step 3: Implement `web/ui_customization.js` controller core**

Follow the UMD pattern. Keep catalog normalization as the only validation path, keep draft and saved snapshots as independent clones, and make each mutation call injected `apply(effectiveState)` without calling `save`.

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m unittest -v test_ui_customization`

Expected: all catalog and controller tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add web/ui_customization.js test_ui_customization.py
git commit -m "feat(ui): add appearance state controller"
```

### Task 3: First-paint bootstrap and static integration

**Files:**
- Modify: `web/index.html`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: `window.JSONCodrUICatalog` from Task 1.
- Produces: root attributes `data-theme`, `data-ui-preset`, `data-ui-density`, `data-ui-typography`, and one `data-ui-<family>` attribute per component family before stylesheets render.
- Loads `/static/ui_catalog.js` synchronously before the bootstrap, then `/static/ui_customization.js` with `defer` before `/static/app.js`.

- [ ] **Step 1: Write failing static integration tests**

Add assertions that:

- `ui_catalog.js` appears before the inline bootstrap and `gamma.css`;
- the bootstrap reads `json_codr_ui_v1`, falls back to `json_codr_theme`, calls catalog normalization/effective-state functions, and sets all required root attributes;
- `ui_customization.js` loads after the catalog and before `app.js`;
- the existing xterm/layout/application ordering remains intact;
- no archive vendor scripts or remote resources appear in `index.html`.

- [ ] **Step 2: Run the targeted tests and verify failure**

Run: `python -m unittest -v test_ui_customization` and, when the known runtime discovery allows FastAPI import, `python -m unittest -v test_web_static.WebStaticTests.test_static_assets_are_served_with_correct_types test_web_static.WebStaticTests.test_theme_settings_and_runtime_hooks_are_present`

Expected: Node-backed tests PASS; static integration assertions FAIL until markup is changed. If FastAPI import remains blocked by the pre-existing Python discovery defect, record it and run equivalent file-content assertions in `test_ui_customization.py` without modifying runtime code.

- [ ] **Step 3: Implement the synchronous bootstrap and script/style tags**

Replace the current standalone `json_codr_theme` head snippet with a guarded catalog bootstrap. On any parse/runtime error, apply `noc-light` defaults directly so the interface remains operable.

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m unittest -v test_ui_customization`

Expected: all bootstrap ordering and fallback assertions PASS.

- [ ] **Step 5: Commit**

```powershell
git add web/index.html test_web_static.py test_ui_customization.py
git commit -m "feat(ui): bootstrap gamma appearance before paint"
```

### Task 4: NOC Light tokens, variants, and approved assets

**Files:**
- Create: `web/gamma.css`
- Create: `web/fonts/fonts.css`
- Create: `web/fonts/opendyslexic-400.woff2`
- Create: `web/fonts/opendyslexic-700.woff2`
- Create: `web/fonts/OpenDyslexic-OFL.txt`
- Create: `web/fonts/THIRD_PARTY_NOTICES.md`
- Modify: `web/app.css`
- Modify: `web/index.html`
- Modify: `test_ui_customization.py`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: root `data-ui-*` attributes from Task 3 and existing stable DOM classes/IDs.
- Produces: semantic tokens used by existing `app.css`, CSS rules for every catalog variant, NOC Light as the no-JavaScript/default appearance, and system fallback for unavailable IBM Plex.

- [ ] **Step 1: Write failing CSS and asset contract tests**

Assert that:

- `gamma.css` defines every preset and every catalog variant attribute;
- `noc-light` defines fixed light `color-scheme`, blue-orange operational accents, compact spacing, flat panels, segmented tabs, and expanded navigation defaults;
- `app.css` consumes semantic tokens rather than overriding NOC Light root values;
- `prefers-reduced-motion`, narrow/mobile navigation, visible focus, and high-contrast variant rules exist;
- only approved font filenames are present under `web/fonts`;
- OpenDyslexic license and provenance notice exist;
- IBM Plex binaries are absent unless an IBM Plex license is present in the same directory.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest -v test_ui_customization`

Expected: FAIL because Gamma CSS/assets do not exist.

- [ ] **Step 3: Copy the approved OpenDyslexic assets**

Copy only these archive entries from `C:\UI\UI.zip`:

- `UI/nocwatch/web/fonts/opendyslexic-400.woff2`
- `UI/nocwatch/web/fonts/opendyslexic-700.woff2`
- `UI/nocwatch/web/fonts/OpenDyslexic-OFL.txt`

Write `THIRD_PARTY_NOTICES.md` with the archive source paths, SHA-256 values, and license reference. Do not copy IBM Plex binaries unless their authoritative license is also added.

- [ ] **Step 4: Implement fonts and Gamma variant CSS**

Create `fonts.css` and `gamma.css`; map existing app variables to semantic Gamma values in `app.css` with the smallest selector changes possible. Preserve xterm-specific colors and existing layout geometry unless a chosen component variant explicitly changes it.

- [ ] **Step 5: Run tests and verify pass**

Run: `python -m unittest -v test_ui_customization`

Expected: catalog/CSS/assets tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add web/gamma.css web/app.css web/index.html web/fonts test_ui_customization.py test_web_static.py
git commit -m "feat(ui): add NOC Light gamma visual system"
```

### Task 5: Appearance editor and existing application bridge

**Files:**
- Modify: `web/index.html`
- Modify: `web/ui_customization.js`
- Modify: `web/app.js`
- Modify: `web/gamma.css`
- Modify: `test_ui_customization.py`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: controller/catalog from Tasks 1–2, root attributes from Task 3, and variants from Task 4.
- Produces: Settings controls with IDs `ui-preset`, `ui-mode`, `ui-density`, `ui-typography`, `ui-component-overrides`, `ui-override-summary`, `ui-preview-status`, `ui-save`, `ui-cancel`, `ui-reset-preset`, and `ui-restore-defaults`.
- Produces: `bindUICustomizationEditor({controller, elements})` in `ui_customization.js`.
- Existing `setting-theme` is removed; `app.js` routes server-loaded `settingsState.ui.theme` only as a legacy seed when no versioned local UI state exists.

- [ ] **Step 1: Write failing editor/controller tests**

Use a minimal fake DOM in Node to assert:

- preset cards/select options come from catalog data rather than duplicated markup values;
- changing a component control previews a root attribute and updates the override count;
- selecting NOC Light disables mode selection with fixed-light help text;
- selecting OpenDyslexic changes compact density to comfortable;
- Cancel restores the snapshot and leaves the storage spy untouched;
- Save persists, clears the legacy key, and announces success;
- Reset component, reset preset, and restore NOC Light defaults produce the exact catalog states.

Add static HTML assertions for every required ID, label association, live region, and button type.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest -v test_ui_customization`

Expected: FAIL because the editor binding and markup do not exist.

- [ ] **Step 3: Implement Appearance editor markup and binding**

Render human labels/descriptions from catalog metadata. Keep raw selectors, CSS variables, and internal variant IDs out of visible explanatory text. Use one editor snapshot per Settings visit and confirm before preset replacement when overrides exist.

- [ ] **Step 4: Bridge `app.js` theme/settings behavior**

Remove direct `json_codr_theme` writes from `applyThemeMode`; delegate local appearance persistence to the controller while retaining the existing serialized `saveSettings({ui:{theme}})` call for local server settings. Keep `setSidebarCollapsed` authoritative for navigation collapse persistence and ensure UI customization never changes `activeDestination`.

- [ ] **Step 5: Run tests and verify pass**

Run: `python -m unittest -v test_ui_customization`

Expected: all editor, persistence, migration, and static accessibility tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add web/index.html web/ui_customization.js web/app.js web/gamma.css test_ui_customization.py test_web_static.py
git commit -m "feat(ui): add configurable appearance editor"
```

### Task 6: Collapsible NOC chrome and end-to-end verification

**Files:**
- Modify: `web/gamma.css`
- Modify: `web/app.js` only if verification exposes a missing bridge
- Modify: `test_ui_customization.py`
- Modify: `test_web_static.py`
- Modify: `docs/superpowers/specs/2026-11-18-gamma-ui-customization-design.md` only for implementation-accurate notes, not scope changes

**Interfaces:**
- Consumes: existing `setSidebarCollapsed(collapsed, {persist})` and Settings `ui.sidebar_collapsed` behavior.
- Produces: NOC Light expanded labeled navigation and a persisted icon-rail collapse state on desktop; existing drawer behavior remains unchanged on narrow/mobile widths.

- [ ] **Step 1: Write failing navigation and regression tests**

Assert that NOC Light CSS:

- keeps labels visible when expanded;
- uses the existing `.sidebar-collapsed` body class to render the icon rail;
- retains focus-visible treatment and at least the existing hit-target sizes;
- does not hide the active destination or alter its `aria-current` state;
- leaves mobile drawer selectors and workspace viewport selectors intact.

Also assert `app.js` still calls `setSidebarCollapsed`, saves only `ui.sidebar_collapsed`, and never couples collapse to preset selection.

- [ ] **Step 2: Run targeted automated tests and verify failure/pass transition**

Run before final CSS adjustments: `python -m unittest -v test_ui_customization`

Expected before adjustment: at least one new collapse-contract assertion FAILS.

Apply the smallest CSS/bridge correction, then rerun until all tests PASS.

- [ ] **Step 3: Run available regression suites**

Run:

```powershell
python -m unittest -v test_ui_customization test_workspace_layout
```

Then run the existing static/settings/workspace suites with whichever existing interpreter can satisfy their unchanged imports. If the known Python 3.14/3.12 discovery contradiction blocks collection, record the exact traceback and do not alter runtime code.

- [ ] **Step 4: Verify the application in a browser**

Start the existing application command without changing runtimes. Check NOC Light default, collapse/expand persistence, all five presets, every component override, save/cancel/reset, reload persistence, keyboard-only navigation, 200% zoom, reduced motion, desktop/narrow/mobile layouts, terminal readability, and task ready/running/stopped/error states.

- [ ] **Step 5: Run repository hygiene checks**

Run:

```powershell
git diff --check
git status --short
```

Confirm no extracted archive files exist outside the approved font manifest and no product code references NOCWatch/Acme business logic.

- [ ] **Step 6: Commit verification adjustments**

```powershell
git add web test_ui_customization.py test_web_static.py docs/superpowers/specs/2026-11-18-gamma-ui-customization-design.md
git commit -m "test(ui): verify gamma customization flows"
```

## Self-review results

- Spec coverage: catalog, presets, component variants, first paint, migration, preview/save/cancel/reset, NOC Light default, collapsible chrome, responsive behavior, accessibility, approved assets, and rollback are assigned to Tasks 1–6.
- Step scan: every task has a failing test, minimal implementation, passing verification, and commit boundary; asset copying is isolated from code changes.
- Type consistency: `JSONCodrUICatalog`, `createUICustomizationController`, state keys, component families, and editor IDs are defined once and consumed consistently.
- Review focus: each listed failure mode has an explicit test owner.
- Proportion: implementation details are expressed as interfaces and assertions; CSS values remain governed by the approved design rather than transcribed into the plan.
