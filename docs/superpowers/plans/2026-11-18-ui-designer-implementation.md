# Structured UI Designer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Settings-enabled structured visual designer that safely customizes JSON_CODR, creates responsive multi-page interfaces, imports sanitized UI references, and exports portable static web bundles.

**Architecture:** A versioned Python-validated scene document is the source of truth, with immutable revisions stored below the JSON_CODR data root. Focused vanilla-JavaScript modules render and edit registered components through serializable commands; JSON_CODR changes are protected overlays, while project canvases may use structured or bounded freeform layouts. Preview and reference rendering run in script-disabled sandboxes, and export translates only registered declarative components and actions.

**Tech Stack:** Python 3.12-compatible FastAPI/Pydantic services, atomic JSON persistence, Python `zipfile`, vanilla JavaScript/CSS, sandboxed iframes, `unittest` with Node-backed browser-module tests.

**Spec:** `docs/superpowers/specs/2026-11-18-ui-designer-design.md`

## Global Constraints

- The design document never stores executable functions, inline scripts, credentials, tokens, cookies, or caller-controlled filesystem paths.
- JSON_CODR shell, navigation, Settings, Designer exit, recovery, approval controls, and terminal behavior bindings are protected.
- Stack/grid are the responsive default; absolute coordinates exist only inside bounded freeform containers.
- External references are disabled by default and limited to explicitly allow-listed HTTPS origins.
- Static export supports only registered components and declarative local actions; connector/file actions export disabled with warnings.
- IBM Plex must not be introduced; bundled and imported fonts must have recorded open-source or user-supplied provenance.
- Existing schema-1 appearance settings remain readable and users who do not enable Designer retain current behavior.

## Review Focus

- Malformed or hostile imported ZIP/JSON/SVG/font input must be rejected without writing outside managed project directories; Task 5 owns these tests.
- Commands applied to deleted, locked, stale-revision, or wrong-project nodes must fail without partial mutation; Tasks 2 and 4 own these tests.
- Freeform-to-responsive breakpoint inheritance must not leak absolute positioning outside its container; Tasks 1 and 4 own these tests.
- Preview/export must never execute imported or user-authored script and must report unsupported connector behavior; Tasks 6 and 7 own these tests.
- JSON_CODR safe mode and recovery controls must remain reachable after invalid or obsolete overlays; Task 10 owns these tests.

---

### Task 1: Scene contracts, settings, and appearance migration

**Files:**
- Create: `web_app/designer/contracts.py`
- Create: `web_app/designer/__init__.py`
- Modify: `web_app/models.py`
- Modify: `web_app/settings.py`
- Test: `test_designer_contracts.py`
- Test: `test_settings.py`

**Interfaces:**
- Consumes: existing Pydantic model conventions and schema-1 `UiSettings`.
- Produces: `DesignDocument`, `DesignPage`, `DesignNode`, `LayoutSpec`, `BreakpointOverride`, `ActionBinding`, `ReferenceRecord`, `DesignerSettings`, and `normalize_design(candidate: object) -> DesignDocument`.

- [ ] **Step 1: Write failing contract and migration tests**

  Test stable canonical digests, unique node/page identifiers, route-safe unique slugs, parent/child consistency, bounded nesting and node counts, structured versus bounded-freeform layout rules, breakpoint inheritance, action allow-lists, unknown inert component preservation, locked capability validation, forbidden executable fields, and schema-1 appearance migration only on first designer save.

- [ ] **Step 2: Run the focused tests and confirm contract symbols are missing**

  Run: `python -m unittest test_designer_contracts.py test_settings.py -v`

- [ ] **Step 3: Implement the minimum immutable contracts and settings schema**

  Add `DesignerSettings(enabled: bool = False, default_mode: Literal["project", "json_codr"] = "project", snap: bool = True, grid_size: int = 8, autosave: bool = True)`. Normalize inherited breakpoint values without materializing redundant overrides. Reject keys matching script, handler, secret, credential, token, cookie, or absolute-path semantics.

- [ ] **Step 4: Run focused tests**

  Run: `python -m unittest test_designer_contracts.py test_settings.py -v`
  Expected: PASS.

- [ ] **Step 5: Commit**

  `git add web_app/designer web_app/models.py web_app/settings.py test_designer_contracts.py test_settings.py && git commit -m "feat(designer): add scene document contracts"`

### Task 2: Atomic project store and immutable revision history

**Files:**
- Create: `web_app/designer/store.py`
- Test: `test_designer_store.py`

**Interfaces:**
- Consumes: `DesignDocument` and canonical digest from Task 1.
- Produces: `DesignerStore(data_root: Path)`, `create_project(template_id, name)`, `get_project(project_id)`, `save_revision(project_id, document, expected_digest)`, `save_draft(project_id, document, expected_digest)`, `list_revisions(project_id)`, `restore_revision(project_id, revision_id, expected_digest)`, and `delete_project(project_id)`.

- [ ] **Step 1: Write failing store tests**

  Cover generated identifiers, atomic writes, optimistic conflicts, immutable parent-linked revisions, draft recovery without replacing explicit saves, reopen reconstruction, project duplication, managed-path confinement, deletion confirmation token, stale/deleted/wrong-project node inputs, and failure injection leaving the previous revision intact.

- [ ] **Step 2: Run tests and confirm `DesignerStore` is absent**

  Run: `python -m unittest test_designer_store.py -v`

- [ ] **Step 3: Implement path-safe atomic storage**

  Store projects beneath `<data_root>/designer/projects/<generated-id>/`; write temporary siblings and replace atomically. Derive all paths from validated identifiers and never accept a filesystem path from an API request.

- [ ] **Step 4: Run focused tests and commit**

  Run: `python -m unittest test_designer_store.py -v`

  `git add web_app/designer/store.py test_designer_store.py && git commit -m "feat(designer): persist versioned design projects"`

### Task 3: Component registry, templates, and protected JSON_CODR manifest

**Files:**
- Create: `web_app/designer/components.py`
- Create: `web_app/designer/templates.py`
- Create: `web_app/designer/json_codr_manifest.py`
- Test: `test_designer_components.py`

**Interfaces:**
- Consumes: scene contracts from Task 1 and existing `web/ui_catalog.js` component families.
- Produces: `ComponentDefinition`, `ComponentRegistry`, `create_template(template_id, name) -> DesignDocument`, `JSON_CODR_MANIFEST_VERSION`, and `create_json_codr_overlay(appearance_state) -> DesignDocument`.

- [ ] **Step 1: Write failing registry tests**

  Assert definitions for containers, stacks, grids, text, heading, button, link, input, textarea, select, checkbox, image, icon, navigation, tabs, card, table, list, form, dialog, divider, spacer, and component instance. Test property schemas, allowed children, semantic exporters, action slots, accessibility requirements, unknown inert placeholders, Blank/Landing Page/Dashboard/Form templates, and the complete protected manifest coverage from the spec.

- [ ] **Step 2: Run tests and confirm missing registry**

  Run: `python -m unittest test_designer_components.py -v`

- [ ] **Step 3: Implement data-only definitions and templates**

  Map NOC Light tokens, existing typography, presets, and component variants into defaults without importing DOM event bindings. Mark protected capability sets explicitly per manifest node.

- [ ] **Step 4: Run focused tests and commit**

  Run: `python -m unittest test_designer_components.py -v`

  `git add web_app/designer/components.py web_app/designer/templates.py web_app/designer/json_codr_manifest.py test_designer_components.py && git commit -m "feat(designer): register components and templates"`

### Task 4: Serializable command engine and browser document model

**Files:**
- Create: `web/designer_model.js`
- Create: `web/designer_commands.js`
- Test: `test_designer_commands.py`

**Interfaces:**
- Consumes: normalized scene JSON and component capability metadata.
- Produces: `createDesignerModel(document, registry)`, `dispatch(command)`, `undo()`, `redo()`, `effectiveNode(nodeId, breakpoint)`, `selection()`, and serializable commands `insert`, `remove`, `move`, `resize`, `group`, `ungroup`, `duplicate`, `reorder`, `set-property`, `set-style`, `set-action`, `set-breakpoint`, and `replace-asset`.

- [ ] **Step 1: Write failing Node-backed unit tests**

  Test every command and inverse, multi-select alignment/distribution, keyboard movement, snapping, layer order, protected-node rejection, stale-node rejection, wrong-project commands, undo limit, group semantics, bounded freeform coordinates, and responsive inheritance without absolute-style leakage.

- [ ] **Step 2: Run tests and confirm modules are missing**

  Run: `python -m unittest test_designer_commands.py -v`

- [ ] **Step 3: Implement pure deterministic modules**

  Keep DOM and network access out of the command engine. Commands carry expected document digest and return `{document, inverse, announcements}` or a structured conflict.

- [ ] **Step 4: Run focused tests and commit**

  Run: `python -m unittest test_designer_commands.py -v`

  `git add web/designer_model.js web/designer_commands.js test_designer_commands.py && git commit -m "feat(designer): add undoable scene commands"`

### Task 5: Managed assets and sanitized reference capture/import

**Files:**
- Create: `web_app/designer/assets.py`
- Create: `web_app/designer/references.py`
- Create: `web_app/designer/capture_adapters.py`
- Create: `web/designer_capture.js`
- Create: `tools/playwright_ui_capture.mjs`
- Create: `tools/make_ui_reference_archive.py`
- Create: `docs/user/ui-reference-capture.md`
- Test: `test_designer_assets.py`
- Test: `test_designer_references.py`

**Interfaces:**
- Consumes: documented legacy capture requirements and project identifiers from Task 2.
- Produces: `AssetService.import_file(project_id, stream, filename, media_type)`, `ReferenceImporter.import_image`, `import_extract`, `import_archive`, `reference_preview`, `CaptureAdapter.describe()`, `CaptureAdapter.capture(request)`, and versioned capture-envelope/`ui-extract.json`/archive schemas.

- [x] **Step 1: Write failing hostile-input and compatibility tests**

  Cover PNG/JPEG/sanitized SVG/font imports, hashes and provenance, maximum sizes, MIME/content mismatch, active SVG content, malformed extracts, forbidden private data fields, ZIP traversal/symlinks/bombs, manifest mismatch, `REVIEW.txt` acknowledgement, unsupported archive versions, inert HTML/CSS preview, authorization/license provenance, adapter versioning, and draft provenance. Playwright fixtures must include DOM/accessibility trees, CSS response bodies, inline styles, safe computed properties, CSS variables/token candidates, image/background/SVG/font inventories, bounded same-origin assets, resource metadata, route/breakpoint screenshots, unresolved cross-origin resources, selector-usage evidence, and framework hints. Assert that scripts, source maps, API payloads, headers, cookies, storage, form values, and authentication state are absent.

- [x] **Step 2: Run tests and verify importers are missing**

  Run: `python -m unittest test_designer_assets.py test_designer_references.py -v`

- [x] **Step 3: Implement managed copies and maintained capture tools**

  The legacy `C:/UI` scripts were unavailable, so define a versioned compatible extract/archive format from the documented exclusions and manifest requirements rather than assuming unknown behavior. Add Playwright as the only first-release browser automation component with no silent browser download. Capture network resources through bounded response handling rather than wget/HTTrack-style mirroring; record selector usage without destructive CSS purging; treat framework detection as advisory. Implement Puppeteer, Storybook, Screenshot-to-Code, React DevTools, FlaUInspect, PyQtInspect, and Applitools only as capability descriptors for later adapters. Never execute imported scripts or silently accept unresolved review findings.

- [x] **Step 4: Run focused tests and commit**

  Run: `python -m unittest test_designer_assets.py test_designer_references.py test_designer_contracts.py test_designer_store.py test_designer_components.py test_designer_commands.py -v` (52 tests passed)

  `git add web_app/designer/assets.py web_app/designer/references.py web_app/designer/capture_adapters.py web/designer_capture.js tools/playwright_ui_capture.mjs tools/make_ui_reference_archive.py docs/user/ui-reference-capture.md test_designer_assets.py test_designer_references.py && git commit -m "feat(designer): import sanitized UI references"`

### Task 6: Lossless CSS parser, import resolver, and cycle bundles

**Files:**
- Create: `tools/ui_capture/css_tokens.mjs`
- Create: `tools/ui_capture/css_parser.mjs`
- Create: `tools/ui_capture/css_resolver.mjs`
- Create: `tools/ui_capture/css_bundler.mjs`
- Create: `tools/ui_capture/css_serializer.mjs`
- Create: `test_designer_css_pipeline.py`
- Create: `test_fixtures/designer_css/comments.css`
- Create: `test_fixtures/designer_css/comments-edge.css`
- Create: `test_fixtures/designer_css/import-cycle/`

**Interfaces:**
- Consumes: captured stylesheet response bodies and resource metadata from Task 5.
- Produces: `tokenizeCss(source, sourceUrl)`, `parseCss(source, sourceUrl)`, `parseImport(tokens)`, `resolveImports(entryUrl, loader, limits)`, `stronglyConnectedComponents(graph)`, `bundleCycles(resolution)`, `serializeCss(ast, options)`, and deterministic source-map/bundle manifests.

- [ ] **Step 1: Write failing tokenizer/parser/round-trip tests**

  Run real Node modules from Python fixtures. Cover strings, escapes, comments with raw interior whitespace and locations, comments between/before/after declarations, consecutive/EOF/license comments, comments inside nested `@layer`/`@media`/`@supports`/`@keyframes`, comment-only and empty blocks, generic simple/block at-rules, and byte-identical golden parse→serialize round trips.

- [ ] **Step 2: Write failing import/resolver/bundle tests**

  Cover quoted and `url(...)` imports, anonymous/named/quoted layers, `supports()`, media text, whitespace/comments, query retention, fragment identity, URL normalization, cache hits, self-imports, depth/count/size limits, cycle paths, Tarjan SCCs, stable bundle names, topological member order, internal-import removal, external-import preservation, duplicate bundle suppression, relative rewrites, asset URLs, source locations, and source-map integrity.

- [ ] **Step 3: Run tests and verify modules are missing**

  Run: `python -m unittest test_designer_css_pipeline.py -v`

- [ ] **Step 4: Implement the lossless token/AST pipeline**

  Preserve raw source slices for unchanged nodes. Only rewritten imports and generated wrappers use canonical formatting. Enforce 32 levels, 512 stylesheets, 5 MiB per stylesheet, and 64 MiB total CSS through the loader boundary; reject non-HTTP(S)/managed URL schemes.

- [ ] **Step 5: Run focused tests and commit**

  Run: `python -m unittest test_designer_css_pipeline.py -v`

  `git add tools/ui_capture test_designer_css_pipeline.py test_fixtures/designer_css && git commit -m "feat(designer): preserve and bundle captured CSS"`

### Task 7: Designer API surface and conflict-safe uploads

**Files:**
- Create: `web_app/designer/api.py`
- Modify: `web_app/app.py`
- Modify: `web_app/models.py`
- Test: `test_designer_api.py`

**Interfaces:**
- Consumes: store, registry, assets, and references from Tasks 2, 3, and 5.
- Produces: `/api/designer/settings`, `/projects`, `/projects/{id}`, `/revisions`, `/draft`, `/restore`, `/assets`, `/references`, `/references/{id}/draft`, `/preview`, and `/export` routes with problem-detail errors and digest conflicts.

- [ ] **Step 1: Write failing API tests**

  Cover disabled-feature behavior, project CRUD, exact-digest saves, stale conflicts, upload streaming limits, generated-ID path confinement, archive acknowledgement, asset/reference download authorization, no local-path leakage, unsupported media, and imported script never appearing in preview responses.

- [ ] **Step 2: Run tests and verify routes return 404**

  Run: `python -m unittest test_designer_api.py -v`

- [ ] **Step 3: Implement a focused router and service injection**

  Mount the router from `create_app`; keep upload bodies streamed to bounded temporary files and delete them on every failure path.

- [ ] **Step 4: Run focused tests and commit**

  Run: `python -m unittest test_designer_api.py -v`

  `git add web_app/designer/api.py web_app/app.py web_app/models.py test_designer_api.py && git commit -m "feat(api): expose visual designer projects"`

### Task 8: Sandboxed renderer, validation, and static export

**Files:**
- Create: `web_app/designer/render.py`
- Create: `web_app/designer/export.py`
- Create: `web/designer_renderer.js`
- Test: `test_designer_render.py`
- Test: `test_designer_export.py`

**Interfaces:**
- Consumes: registered components/actions, managed assets, normalized documents, and lossless CSS bundles from Task 6.
- Produces: `validate_for_preview(document)`, `render_preview(document, allowlist)`, `StaticExportService.export(project_id, revision_id) -> Path`, and browser `renderScene(root, document, options)`.

- [ ] **Step 1: Write failing renderer/export tests**

  Assert semantic elements, responsive stack/grid/freeform CSS, multi-page paths, relative assets, CSP allow-list generation, no inline/evaluated code, no imported scripts, accessibility blocking errors, warning-only contrast issues, disabled connector/file actions with inert metadata, HTTPS form handling, deterministic ZIP contents, and screenshot-comparison reports across captured routes and breakpoints without claiming pixel identity.

- [ ] **Step 2: Run tests and verify renderer is absent**

  Run: `python -m unittest test_designer_render.py test_designer_export.py -v`

- [ ] **Step 3: Implement registry-driven rendering and export**

  Escape all text/attributes, generate CSS from validated token/style values, use a sandbox without same-origin or script permission for reference content, and include `design.json`, validation report, pages, CSS, optional bounded action interpreter, and assets.

- [ ] **Step 4: Run focused tests and commit**

  Run: `python -m unittest test_designer_render.py test_designer_export.py -v`

  `git add web_app/designer/render.py web_app/designer/export.py web/designer_renderer.js test_designer_render.py test_designer_export.py && git commit -m "feat(designer): render and export safe interfaces"`

### Task 9: Settings enablement and designer application shell

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/app.css`
- Modify: `web/gamma.css`
- Create: `web/designer_app.js`
- Create: `web/designer.css`
- Test: `test_designer_ui.py`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: Designer settings/API and renderer from Tasks 7 and 8.
- Produces: Settings enable/default/snap/grid/autosave controls and a Designer destination with command bar, left library/pages/layers/templates/reference panel, canvas, right inspector, and live status region.

- [ ] **Step 1: Write failing static and interaction tests**

  Test disabled/visible destination behavior, project/template creation, page switching, save state, breakpoint controls, zoom, preview/export, responsive panel collapse, accessible labels, focus order, live announcements, keyboard-only panel access, 200% zoom, reduced motion, and safe exit.

- [ ] **Step 2: Run tests and confirm Designer markup is missing**

  Run: `python -m unittest test_designer_ui.py test_web_static.py -v`

- [ ] **Step 3: Implement the shell without embedding editor logic in `app.js`**

  Lazy-initialize `designer_app.js` only when enabled and selected. Preserve Workspace and current NOC Light/theme behavior.

- [ ] **Step 4: Run focused tests and commit**

  Run: `python -m unittest test_designer_ui.py test_web_static.py -v`

  `git add web/index.html web/app.js web/app.css web/gamma.css web/designer_app.js web/designer.css test_designer_ui.py test_web_static.py && git commit -m "feat(ui): add visual designer workspace"`

### Task 10: Canvas manipulation, inspector, and reference drafting

**Files:**
- Create: `web/designer_canvas.js`
- Create: `web/designer_inspector.js`
- Modify: `web/designer_app.js`
- Modify: `web/designer.css`
- Test: `test_designer_canvas.py`
- Test: `test_designer_inspector.py`

**Interfaces:**
- Consumes: Task 4 command engine, Task 8 renderer, and Task 9 shell.
- Produces: pointer/keyboard selection, drag, resize, drop, alignment, grouping, layers, snapping, device bounds, and Content/Layout/Style/Typography/Asset/Actions/Accessibility/Advanced inspectors.

- [ ] **Step 1: Write failing browser-module tests**

  Test pointer capture cancellation, keyboard parity, multi-selection, resize boundaries, snapping toggles, drop validation, locked nodes, all standard style/font/image controls, action validation, reference opacity/placement, `Create draft from reference`, undo/redo, and stale-save conflict refresh.

- [ ] **Step 2: Run tests and verify controllers are missing**

  Run: `python -m unittest test_designer_canvas.py test_designer_inspector.py -v`

- [ ] **Step 3: Implement controllers as command producers**

  Keep pointer arithmetic and form binding separate from scene mutation. Reference-derived nodes must show provenance and require review before the first explicit save.

- [ ] **Step 4: Run focused tests and commit**

  Run: `python -m unittest test_designer_canvas.py test_designer_inspector.py -v`

  `git add web/designer_canvas.js web/designer_inspector.js web/designer_app.js web/designer.css test_designer_canvas.py test_designer_inspector.py && git commit -m "feat(designer): add canvas and property inspector"`

### Task 11: Protected JSON_CODR overlay, rebase, and safe mode

**Files:**
- Create: `web/designer_overlay.js`
- Modify: `web/ui_catalog.js`
- Modify: `web/ui_customization.js`
- Modify: `web/ui_bootstrap.js`
- Modify: `web/index.html`
- Test: `test_designer_overlay.py`
- Modify: `test_ui_customization.py`

**Interfaces:**
- Consumes: protected manifest from Task 3, commands from Task 4, and existing schema-1 customization controller.
- Produces: `createOverlayController({manifest, document, catalog})`, manifest-version rebase, startup bypass `JSON_CODR_SAFE_UI=1`, persistent Exit Designer, overlay reset, and schema-1-to-schema-2 migration on save.

- [ ] **Step 1: Write failing overlay and recovery tests**

  Cover approved property changes, forbidden remove/rebind/out-of-region changes, required control reachability, invalid overlay disable-and-preserve, manifest rebase success/failure, old theme state preservation, safe-mode startup, reset only customization, and corrupted local cache.

- [ ] **Step 2: Run tests and confirm overlay controller is absent**

  Run: `python -m unittest test_designer_overlay.py test_ui_customization.py -v`

- [ ] **Step 3: Implement overlay application after base UI bootstrap**

  Keep behavior bindings in the base UI. Apply only validated classes, tokens, assets, visibility, and region-safe layout properties. Safe mode must bypass all designer storage before rendering.

- [ ] **Step 4: Run focused tests and commit**

  Run: `python -m unittest test_designer_overlay.py test_ui_customization.py -v`

  `git add web/designer_overlay.js web/ui_catalog.js web/ui_customization.js web/ui_bootstrap.js web/index.html test_designer_overlay.py test_ui_customization.py && git commit -m "feat(designer): protect JSON_CODR customization"`

### Task 12: End-to-end verification, documentation, and release integration

**Files:**
- Create: `test_designer_e2e.py`
- Modify: `README.md`
- Create: `docs/user/ui-designer.md`
- Modify: `docs/user/ui-reference-capture.md`
- Modify: `web_app/version.py`
- Modify: `test_version.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented enable/customize/create/import/save/recover/export workflows and verified release identity.

- [ ] **Step 1: Write end-to-end scenarios**

  Exercise enabling Designer; creating a Landing Page; adding, moving, resizing, styling, and reimaging elements; desktop/tablet/mobile overrides; multi-page navigation; save/restart/reopen; screenshot, `ui-extract.json`, and archive references; draft generation; sandbox preview; static export inspection; JSON_CODR overlay; invalid-overlay safe mode; and keyboard-only editing.

- [ ] **Step 2: Run focused integration tests and fix only integration defects**

  Run: `python -m unittest test_designer_e2e.py -v`

- [ ] **Step 3: Update user documentation and release identity**

  Document capture privacy boundaries, archive sanitization reports, unsupported executable behavior, safe mode, open-source font policy, static-export limitations, and future exporter adapters. Choose the next numerical prerelease after reconciling the existing alpha.12 release work; update cache-busting query strings and version tests together.

- [ ] **Step 4: Run full verification**

  Run:
  - `python -m unittest discover -v`
  - `python -m compileall -q web_app`
  - JavaScript syntax checks for every new browser module
  - `git diff --check`

  Expected: all tests pass, compilation/syntax checks succeed, and only intended files remain changed.

- [ ] **Step 5: Perform local smoke verification**

  Start with the documented Python 3.12-compatible runtime split, enable Designer, complete one JSON_CODR overlay and one project/reference/export flow, inspect the exported site offline, then restart in safe mode and verify recovery controls.

- [ ] **Step 6: Commit**

  `git add test_designer_e2e.py README.md docs/user web_app/version.py test_version.py web/index.html && git commit -m "release: integrate structured UI designer"`

## Final verification gate

Before publication, request an independent code review against the approved spec, resolve findings, rerun the full verification from a fresh process, and inspect a generated export manually. Do not publish if imported content can execute, any protected JSON_CODR control can become unreachable, project paths escape the managed root, stale commands partially apply, an unsupported connector action remains active in an export, or the supplied capture formats lose their privacy exclusions.
