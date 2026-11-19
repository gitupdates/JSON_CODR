# Theme Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an accessible Indigo light theme with persisted Light, Dark, and System appearance modes, then verify it in the internal browser.

**Architecture:** The Settings API remains authoritative and stores a validated theme mode. The browser applies an effective light/dark theme through `data-theme`, mirrors the last server value in local storage for early paint, and listens to `prefers-color-scheme` while System is selected. Semantic CSS variables provide both palettes without restructuring the UI.

**Tech Stack:** Python 3.13, Pydantic, FastAPI, unittest, static HTML/CSS, browser JavaScript

**Spec:** `docs/superpowers/specs/2026-11-13-theme-settings-design.md`

## Global Constraints

- Valid stored values are exactly `light`, `dark`, and `system`.
- Default to `dark` so existing installations keep their current appearance.
- The Indigo clarity palette must retain high-contrast text, controls, borders, and focus indicators.
- System mode must react to Windows appearance changes without reloading.
- Browser storage is an early-render cache, never the authoritative setting.
- Preserve unknown existing settings fields and the current dark visual identity.

## Review Focus

- A legacy settings file with no theme loads as dark; Task 1 adds a migration/default test.
- An unsupported theme sent to the API returns validation failure; Task 1 adds an API test.
- A corrupt local-storage value is ignored and dark is used until the API responds; Task 2 adds a static behavior contract test.
- System mode changes when the media query changes and manual modes do not; Task 2 adds a listener contract test.
- A failed settings save restores the prior theme and cache; Task 2 adds a rollback contract test.

---

### Task 1: Persist and validate theme mode

**Files:**
- Modify: `web_app/models.py`
- Modify: `test_settings.py`

**Interfaces:**
- Produces: `UiSettings.theme: Literal["light", "dark", "system"]`, default `"dark"`
- Consumes: existing `SettingsService.update(SettingsUpdate)` merge and unknown-field preservation

- [ ] **Step 1: Write failing model and API tests**

Add assertions that a new and legacy settings record defaults to `dark`, each valid value round-trips through `PATCH /api/settings`, and an unsupported value returns HTTP 422.

- [ ] **Step 2: Run the focused tests and verify red**

Run: `python -m unittest -v test_settings.py`
Expected: FAIL because `UiSettings` has no `theme` field or the API drops it.

- [ ] **Step 3: Add the validated field**

Import `Literal` and define `theme: Literal["light", "dark", "system"] = "dark"` on `UiSettings`.

- [ ] **Step 4: Run the focused tests and verify green**

Run: `python -m unittest -v test_settings.py`
Expected: all settings tests PASS.

### Task 2: Apply accessible themes in the browser

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/app.css`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: `settingsState.ui.theme` from Task 1
- Produces: `applyThemeMode(mode)`, document `data-theme="light|dark"`, local cache key `json_codr_theme`, and the `#setting-theme` Light/Dark/System selector

- [ ] **Step 1: Write failing static behavior-contract tests**

Assert that the rendered Settings panel contains `setting-theme`; JavaScript contains the valid-mode guard, local cache key, `matchMedia('(prefers-color-scheme: dark)')`, a change listener, and rollback path; CSS contains a light theme selector and semantic focus, surface, input, terminal, and error variables.

- [ ] **Step 2: Run the focused tests and verify red**

Run: `python -m unittest -v test_web_static.py`
Expected: FAIL because the selector and theme hooks do not exist.

- [ ] **Step 3: Add early theme initialization and the Settings control**

In `index.html`, add an early script that accepts only `light`, `dark`, or `system` from `json_codr_theme`, resolves System through `matchMedia`, applies `data-theme`, and sets `colorScheme`. Add a labeled native select with all three modes under Interface.

- [ ] **Step 4: Add runtime theme behavior**

In `app.js`, normalize modes, compute/apply the effective theme, mirror API values into `json_codr_theme`, listen for system changes, and apply selection immediately. Save with `saveSettings({ ui: { skill_catalog_open, theme } })`; on failure restore the previous mode/cache and show the existing error UI.

- [ ] **Step 5: Convert the stylesheet to semantic theme variables**

Keep current values as dark defaults. Add Indigo clarity light values under `:root[data-theme="light"]`, replace hardcoded page/panel/text/input/button/focus/error/terminal colors with semantic variables, and set native `color-scheme` consistently.

- [ ] **Step 6: Run focused tests and verify green**

Run: `python -m unittest -v test_settings.py test_web_static.py`
Expected: all focused tests PASS.

### Task 3: Full verification and internal-browser reload

**Files:**
- Verify: all changed files

**Interfaces:**
- Consumes: completed settings and browser theme behavior
- Produces: a healthy relaunched service and verified Light/Dark/System UI
