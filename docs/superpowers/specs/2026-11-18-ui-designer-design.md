# UI Designer Design

## Intent

JSON_CODR will provide one visual designer for two related jobs: safely customizing JSON_CODR's own interface and creating new interfaces, websites, and program front ends on a separate canvas. The goal is to let an end user arrange and style an interface visually while keeping the result editable, portable, accessible, and recoverable.

## Goals

- Add an **Enable UI Designer** control under Settings and a visible Designer destination when enabled.
- Use the same structured document model for JSON_CODR customization and new projects.
- Let users select, move, resize, reorder, duplicate, hide, and delete eligible elements.
- Let users replace images and icons and edit text, font family, font size, weight, line height, letter spacing, alignment, color, background, border, radius, shadow, spacing, and layout properties.
- Provide standard elements: containers, stacks, grids, text, headings, buttons, links, inputs, text areas, selects, checkboxes, images, icons, navigation, tabs, cards, tables, lists, forms, dialogs, dividers, spacers, and embedded component instances.
- Support desktop, tablet, and mobile breakpoints with explicit per-breakpoint overrides.
- Provide undo, redo, copy, paste, duplicate, keyboard movement, alignment, distribution, layer ordering, snapping, zoom, preview, and reset.
- Save named projects locally through the existing Python service and maintain versioned revisions.
- Export a project as a self-contained standards-based HTML/CSS/JavaScript bundle plus its portable JSON design document.
- Preserve the current theme presets and developer-editable component mappings as reusable design tokens and component defaults.
- Capture or import another interface as a sanitized visual and structural reference without importing its executable behavior.

## Non-goals for the first release

- Generating arbitrary native desktop or mobile binaries.
- Executing user-authored JavaScript inside the JSON_CODR application origin.
- Replacing a full source-code IDE, raster image editor, or vector illustration package.
- Collaborative real-time editing, cloud hosting, or a public template marketplace.
- Pixel-perfect import of arbitrary third-party websites.

These can be added later through export adapters, plugins, and connectors without changing the core design document.

## Anti-goals

- A raw DOM editor that can detach JSON_CODR controls from their event handlers.
- Saving absolute machine paths, credentials, or remote-access tokens in a design.
- Allowing a visual edit to make essential JSON_CODR navigation, Settings, recovery, or accessibility controls unreachable.
- Binding behavior through inline scripts or string-evaluated code.

## Chosen approach

The user selected a **structured shared designer**. A versioned JSON scene document is the source of truth. The renderer produces DOM from registered component definitions, and editing commands mutate the scene document rather than arbitrary live markup.

Two modes share the engine:

1. **Customize JSON_CODR** starts from a protected manifest of the live application. Editable regions expose approved layout, asset, typography, visibility, and style properties. Essential controls and behavior bindings are locked. Changes are stored as an overlay, so an application upgrade can rebase them or return to NOC Light.
2. **Create project** starts with a blank canvas or template. All project-owned nodes may be arranged and removed. Behavior comes from a constrained action catalog, such as navigate, open dialog, submit form, switch tab, set value, or invoke an explicitly approved connector.

The user approved a **hybrid layout model**. Stack and grid containers are the responsive default. A freeform container may position children anywhere within its own bounded coordinate space while the container itself participates in normal responsive flow. Grouping selected project nodes creates a stack, grid, or freeform container; locked JSON_CODR nodes cannot be grouped. Breakpoint-specific position and size overrides apply only where explicitly set.

## Alternatives considered

### Direct DOM editing

This provides maximum immediate freedom but can break navigation, event handlers, accessibility, and upgrades. It was rejected because the user also needs JSON_CODR itself to remain usable after editing.

### Separate customization and page-builder systems

This isolates risk but duplicates inspectors, component definitions, persistence, and export logic. It was rejected because layouts and components should transfer between JSON_CODR customization and user-created projects.

## Document and component model

Each design document has a schema version, project identity, canvas metadata, token set, asset references, component tree, breakpoint overrides, action bindings, and revision metadata. Every node has a stable generated identifier, registered component type, parent, ordered children where applicable, properties, styles, constraints, accessibility metadata, and optional locked capabilities.

Projects are multi-page in the first release. Each page has a route-safe slug and component root; shared tokens, assets, and reusable components live at project scope. Static export writes `index.html` for the home page and one `<slug>/index.html` for each additional page, so navigation works without requiring a client-side router.

Component definitions declare:

- allowed children and editable properties;
- default tokens and responsive behavior;
- action slots and data-binding slots;
- renderer and export renderer;
- accessibility requirements;
- capabilities allowed in JSON_CODR mode versus project mode.

Unknown component types remain in the document as inert placeholders instead of being discarded. Invalid values are rejected at the command boundary. The document format never stores executable functions.

## Designer experience

Settings contains the enable switch, default canvas mode, grid and snapping defaults, autosave preference, and recovery/reset controls. Enabling it adds a Designer destination without replacing Workspace.

The Designer has:

- a top command bar for project, device breakpoint, undo/redo, preview, save, and export;
- a left panel for pages, layers, templates, and the component library;
- a central canvas with selection outlines, resize handles, drop targets, rulers, grid, zoom, and breakpoint bounds;
- a right inspector with Content, Layout, Style, Typography, Asset, Actions, Accessibility, and Advanced sections;
- a status region for save state, validation issues, keyboard guidance, and announcements.

Direct manipulation and inspector edits issue the same serializable commands. Selection, panels, and keyboard focus are coordinated so the designer remains operable without a pointer. The canvas supports multi-select, but JSON_CODR locked nodes cannot be grouped, moved outside their allowed region, or deleted.

The built-in starting choices are Blank, Landing Page, Dashboard, and Form. They use only built-in components and locally available assets, making them examples of the portable format rather than privileged code paths.

The first JSON_CODR manifest covers the application shell, primary navigation, top bar, Workspace regions, context/files panel, Skills panel, Hardware panel, Settings panel, composer, response cards, plan/review panels, status indicators, and terminal container. Shell, navigation, Settings, Designer exit, recovery, approval controls, and terminal behavior bindings are protected. Their approved visual properties may change, but they cannot be removed, renamed, rebound, or placed outside their declared region.

## Assets and fonts

Imported images, SVGs, and fonts are copied into the project's managed asset directory using generated names and content hashes. The service validates type and size, blocks active SVG scripting and path traversal, and records license/source metadata when supplied. External URLs are references only and require an explicit network-capable preview or export policy.

The first release includes system font stacks and the existing open-source OpenDyslexic asset. Additional font files may be imported only in supported web formats. IBM Plex is not reintroduced. Export emits local relative asset paths and font declarations.

## Reference capture and import

The Designer includes a **Reference** panel with three user-initiated import paths:

1. Import PNG, JPEG, or sanitized SVG screenshots as locked reference layers that can be positioned beside or behind the canvas with adjustable opacity.
2. Import a `ui-extract.json` structural summary produced by the supplied browser-console capture workflow. It may provide viewport size, page names, headings, labels, control types, class-frequency hints, grid columns, and element bounds, but never table-cell content, input values, query strings, credentials, or hostnames.
3. Import a sanitized UI archive ZIP produced by the supplied `make_ui_archive.py` workflow. The importer verifies `MANIFEST.sha256`, reads `REPORT.md` and `DIFF.md`, rejects traversal and oversized entries, and refuses archives containing `REVIEW.txt` unless the user explicitly acknowledges that the archive has unresolved sanitization findings.

The existing `C:/UI/extract_ui.js` and `C:/UI/make_ui_archive.py` define the initial compatible capture formats. Maintained copies, format schemas, and instructions will ship with JSON_CODR so captures do not depend on those machine-specific paths.

Imported references are inert: scripts, event handlers, forms, remote requests, cookies, storage, and application data never execute. HTML/CSS source from an archive is rendered only through a sanitizer in a script-disabled sandbox. The user may inspect colors, typography, spacing, assets, and structure, then choose **Create draft from reference** to generate editable registered components. Generated nodes are a reviewable draft and retain provenance back to the reference; they are not treated as a pixel-perfect or behavior-preserving clone.

Reference files are copied into the project's managed reference directory with content hashes and source/license notes. Deleting a reference does not delete components already created from it. Reference capture is always an explicit user action and does not crawl authenticated sites or bypass access controls.

## Persistence and history

Python owns project persistence beneath the configured JSON_CODR data root. Writes are atomic. Each save creates an immutable revision with parent revision, timestamp, schema version, and content digest. Autosave maintains a recoverable draft without replacing the last explicit save. Users can restore a previous revision, duplicate a project, import a JSON design, or reset only the JSON_CODR customization overlay.

The browser may cache transient selection and panel state, but the authoritative design and assets are not localStorage-only. Project APIs use identifiers rather than caller-provided filesystem paths.

## Preview, actions, and export

Edit mode never runs project actions. Preview renders in a sandboxed iframe with a restrictive content security policy. The action catalog is declarative; connector or file actions show their required effects and use the existing approval system at runtime.

The first-release action catalog is intentionally bounded: navigate to a project page or approved URL, open/close a dialog, switch a tab, toggle visibility, set a local value, reset a form, submit a form to an explicitly configured HTTPS endpoint, and request an approved JSON_CODR connector action. Local values live for the preview session unless represented by a form field; the design contains no general expression language or arbitrary data-fetch binding. Action arguments are schema-validated and connector/file effects remain approval-gated.

Static exports support local actions, page navigation, approved URL navigation, and HTTPS form submission. JSON_CODR connector/file actions export as disabled controls with a validation warning and an inert metadata marker; they never receive credentials or bypass the host approval system. Future runtime adapters may implement those markers explicitly.

Export produces:

- `design.json`, the portable source document;
- semantic `index.html`;
- generated `styles.css` with tokens and breakpoint rules;
- a small `app.js` interpreter only when declarative actions require it;
- a relative `assets/` directory;
- an export report listing validation warnings and unsupported capabilities.

The initial export target is a static web bundle. The component/export registry is intentionally adapter-ready so later revisions can add React, desktop-shell, or framework-specific output without coupling those dependencies to the core editor.

External network references are disabled in preview by default. A project can allow-list HTTPS origins for images, links, and form destinations separately; preview CSP is generated from that list. Export preserves allowed references and reports them, but does not silently download or embed remote content. Importing an asset copies it into the managed project instead.

## Safety and recovery

JSON_CODR customization is applied as an overlay to a known manifest version. Required navigation, Settings, Designer exit, save/cancel, and recovery controls cannot be deleted or hidden. A persistent **Exit Designer** command and a startup safe-mode flag bypass customization. If an overlay cannot be rebased after an upgrade, it is disabled and preserved for review.

Destructive design actions are undoable within the session. Replacing an explicit saved revision or deleting a project requires confirmation. Imported documents are schema-validated with bounded node counts, nesting depth, text lengths, and asset sizes before rendering.

## Accessibility and responsive behavior

The designer itself targets keyboard operation, visible focus, screen-reader announcements, 200% zoom, reduced motion, and high contrast. Components declare accessible names and semantic roles. Validation blocks export for missing required form labels or inaccessible locked navigation and warns for contrast, empty alternative text, heading-order, and touch-target issues.

Breakpoint overrides inherit from the next larger layout unless explicitly changed. Canvas resizing previews fluid widths between named breakpoints. Exported markup retains semantic elements rather than converting the design to an absolute-positioned picture.

## Compatibility and migration

The existing `ui_catalog.js` presets, typography choices, and component variants become seed tokens and registered component defaults. Existing schema-1 appearance state remains readable and is migrated into a schema-2 JSON_CODR overlay on first designer save. Users who never enable the designer retain current behavior.

The UI remains dependency-light and works with the current Python/FastAPI service and plain browser JavaScript. A small permissively licensed interaction library may be vendored only if its license and source are recorded; otherwise pointer and keyboard interactions remain native.

## Testing and acceptance

- Contract tests validate normalization, migration, unknown components, constraints, actions, and revision digests.
- Service tests validate atomic persistence, traversal protection, asset validation, revisions, import, and export.
- Reference tests validate screenshot layers, extract-schema bounds, archive manifests, ZIP traversal protection, sanitization warnings, inert previews, and provenance on generated drafts.
- Browser/unit tests validate command history, drag/resize math, breakpoint inheritance, locked nodes, and inspector changes.
- Integration tests create a project, add and style elements, save, reload, preview, export, and inspect the bundle.
- JSON_CODR-mode tests prove essential controls remain reachable and safe mode restores the uncustomized interface.
- Accessibility tests cover keyboard-only editing, focus order, announcements, labeling, zoom, and reduced motion.

The feature is complete when an end user can enable Designer, customize an allowed JSON_CODR region without breaking application behavior, build a responsive multi-element interface from a blank canvas, save and reopen it, and export a working static web bundle with no executable content stored in the design document.

## Builder decisions

The builder may choose focused module names, internal data structures, native pointer implementation versus a permissively licensed vendored interaction library, exact visual spacing, and performance thresholds that do not weaken the bounded-import and accessibility requirements. Framework-specific and native application exporters remain future adapters.
