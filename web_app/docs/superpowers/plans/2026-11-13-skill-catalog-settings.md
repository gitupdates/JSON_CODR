# Skill Catalog and Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent, cross-model installed-skill catalog with details, Markdown export, explicit folder discovery, confirmed known-location fallback, and Settings-controlled visibility.

**Architecture:** Add an atomic versioned settings service and extend the existing skill service with documentation and bounded discovery previews. FastAPI handlers expose thin JSON/download contracts. The existing vanilla JavaScript client gains dedicated Skills and Settings panels backed by the APIs, while the prompt-context path remains provider-neutral.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest, vanilla JavaScript/HTML/CSS, Playwright CLI for integrated verification.

**Spec:** `docs/superpowers/specs/2026-11-13-skill-catalog-settings-design.md`

## Global Constraints

- Initial catalog content is installed JSON_CODR skills only.
- No automatic drive scan, background watcher, remote marketplace, or silent installation.
- Known-location discovery requires an unexpired token produced by an empty explicit scan.
- Preview state expires after ten minutes and installation revalidates source identity and digest.
- Global `enabled` and per-session `selected` semantics remain unchanged.
- Existing skill catalogs and session manifests load without user migration.

## Review Focus

- Symlink/reparse-point or escaping scan roots must be rejected or contained; Task 2 tests this.
- Large/deep directory trees must stop at the fixed bounds and return warnings; Task 2 tests this.
- A source modified after preview must not install; Task 2 tests this.
- Unknown settings keys must survive supported updates; Task 1 tests this.
- Legacy skills lacking structured metadata must still export useful documentation; Task 2 tests this.

---

### Task 1: Persistent System Settings

**Files:**
- Create: `web_app/settings.py`
- Modify: `web_app/models.py`
- Modify: `web_app/app.py`
- Test: `test_settings.py`

**Interfaces:**
- Produces: `SystemSettings`, `SettingsUpdate`, and `SettingsService.get()`, `SettingsService.update(update)`.
- Produces: `GET /api/settings` and `PATCH /api/settings`.

- [ ] **Step 1: Write failing service tests** for defaults, atomic persistence across service instances, approved-directory removal, and preservation of an unknown top-level key inserted into the JSON file.
- [ ] **Step 2: Run `python -m pytest test_settings.py -q`** and verify failures are caused by the missing settings service/models.
- [ ] **Step 3: Implement models and `SettingsService`** using `<data_root>/settings.json`, schema version `1`, resolved unique approved directories, and temporary-file plus `os.replace` writes.
- [ ] **Step 4: Write failing API tests** proving GET defaults and PATCH persists `ui.skill_catalog_open` and `skill_scan.approved_directories`.
- [ ] **Step 5: Implement thin settings endpoints** in `create_app`, sharing the workspace data root.
- [ ] **Step 6: Run `python -m pytest test_settings.py -q`** and verify all Task 1 tests pass.
- [ ] **Step 7: Commit** with `feat(settings): add persistent system configuration`.

### Task 2: Skill Details, Documentation, and Discovery

**Files:**
- Modify: `web_app/models.py`
- Modify: `web_app/skills.py`
- Modify: `web_app/app.py`
- Modify: `test_skills.py`

**Interfaces:**
- Consumes: `SettingsService.update()` for approved scan directories.
- Produces: `SkillLibraryService.documentation(pack_id, skill_id) -> str`.
- Produces: `SkillDiscoveryService.scan(directory)`, `scan_known(token)`, and `install(discovery_id)` with process-local ten-minute previews.
- Produces: scan, known-scan, discovery-install, and Markdown download endpoints from the spec.

- [ ] **Step 1: Write failing documentation tests** asserting legacy skill Markdown contains name, intent, abilities, command syntax, examples, compatibility, and converted instructions.
- [ ] **Step 2: Run the focused test** and verify failure is the missing documentation interface.
- [ ] **Step 3: Implement deterministic metadata derivation and Markdown generation** without rewriting legacy catalog records.
- [ ] **Step 4: Write failing explicit-discovery tests** for a recognized folder pack, an archive, duplicate labeling, empty scan fallback token, invalid directory, reparse/symlink containment, depth/entry bounds, and source mutation after preview.
- [ ] **Step 5: Run the discovery tests** and verify they fail because discovery is absent.
- [ ] **Step 6: Implement `SkillDiscoveryService`** with opaque UUIDs, digest revalidation, ten-minute monotonic expiry, bounded caches, warnings, and conversion through `SkillConverterService`.
- [ ] **Step 7: Write failing known-location tests** proving a missing/expired token is rejected and only bounded user-level provider roots are inspected.
- [ ] **Step 8: Implement confirmed known-location discovery** and consume the fallback token once used.
- [ ] **Step 9: Write failing API tests** for previews being non-mutating, reviewed install, duplicate-disabled results, validation status codes, and Markdown attachment headers/content.
- [ ] **Step 10: Implement thin discovery and documentation endpoints** and record only successfully scanned explicit directories as approved.
- [ ] **Step 11: Run `python -m pytest test_skills.py test_settings.py -q`** and verify all Task 1–2 tests pass.
- [ ] **Step 12: Commit** with `feat(skills): add discovery and documentation`.

### Task 3: Skills Catalog and Settings UI

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/app.css`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: settings, installed skills, documentation, scan, known-scan, and install-discovery APIs.
- Produces: collapsible `#skills-panel`, `#settings-panel`, details display, download links, scan review, and conditional known-location prompt.

- [ ] **Step 1: Extend static tests first** to require Skills and Settings top-bar controls, both panels, accessible detail/scan regions, and documentation links; run `python -m pytest test_web_static.py -q` and verify the expected missing-element failures.
- [ ] **Step 2: Add semantic panel markup** and replace the duplicate compact Context catalog with one action that opens Skills.
- [ ] **Step 3: Add failing source-contract assertions** for API-backed persisted visibility, Details rendering, explicit scan preview, conditional known-location action, approved-directory rescan/remove, and reviewed installation.
- [ ] **Step 4: Implement client behavior** with generation-safe rendering, settings-authoritative visibility, structured detail fallbacks, and scoped errors.
- [ ] **Step 5: Add responsive CSS** for catalog rows, detail cards, discovery results, and Settings while retaining the current visual system and avoiding continuous animation.
- [ ] **Step 6: Run `node --check web/app.js` and `python -m pytest test_web_static.py -q`** and verify clean output.
- [ ] **Step 7: Commit** with `feat(web): add skill catalog and settings panels`.

### Task 4: Integration, Documentation, and Live Retest

**Files:**
- Modify: `README.md`
- Test: entire existing pytest suite

**Interfaces:**
- Consumes: all prior task interfaces.
- Produces: user guidance and a verified live V1 application on port `8772`.

- [ ] **Step 1: Update the existing README feature/use sections** with installed-skill details, export, Settings persistence, explicit folder scanning, and the conditional known-location scan.
- [ ] **Step 2: Run `python -m pytest -q`, `node --check web/app.js`, and `git diff --check`** and require zero failures/errors.
- [ ] **Step 3: Restart only the tracked JSON_CODR process on port 8772** with the existing runtime data root and confirm `/api/health`, `/api/settings`, and `/api/skills` return successfully.
- [ ] **Step 4: Use Playwright CLI against `http://127.0.0.1:8772/`** to verify Skills minimize/reopen after reload, one installed pack, skill Details, Markdown download, Settings approved-directory controls, empty explicit scan, and the conditional known-location offer.
- [ ] **Step 5: Inspect `git status`, commit the approved design/plan plus README or amend only if prior task commits deliberately excluded them**, and report the live URL, test counts, and commit IDs.

## Self-Review

- Spec coverage: every goal, non-goal, API, UI state, cross-model rule, and verification item maps to Tasks 1–4.
- Step scan: each step is one test, implementation, verification, or commit action; no task assumes an unnamed interface.
- Type consistency: `SettingsService`, `SkillDiscoveryService`, and `SkillLibraryService.documentation` names remain consistent across producers and consumers.
- Review focus: the five highest-risk unspoken cases each have an owning Task 1 or Task 2 test.
- Proportion: implementation details are limited to contracts and safety values that a builder cannot infer from the existing code.
