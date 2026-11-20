# JSON_CODR Global Navigation Sidebar Design

## Intent

Replace the growing collection of top-bar panel toggles and the oversized Hardware Optimization settings block with one persistent application navigation system. The sidebar should make Chat, CLI, Context, Skills, Hardware, and Settings easy to find while giving the working area more room and keeping advanced hardware features organized.

The design serves users who move repeatedly between local model chat, attached context, skills, terminal work, and system configuration. It favors compatibility, clear status, and predictable navigation over dense presentation.

## Goals

- Provide one global navigation sidebar across the JSON_CODR interface.
- Make the sidebar collapsible and mouse-resizable on wide screens.
- Persist the sidebar width, collapsed state, and last selected destination across restarts through the existing UI settings mechanism.
- Replace the current CLI, Context, Skills, and Settings top-bar buttons with sidebar destinations.
- Organize Hardware Optimization into focused destinations without changing its existing operations or compatibility-first behavior.
- Use a consistent, clean precision-outline SVG icon family with text labels in expanded mode and accessible labels/tooltips in collapsed mode.
- Preserve keyboard access and existing panel shortcuts.
- Keep the layout usable in both light and dark themes and at narrow viewport widths.

## Non-goals

- Redesigning model chat, terminal execution, skill conversion, attachment processing, hardware detection, benchmark algorithms, or LocalPerf data formats.
- Adding a new frontend framework, icon dependency, router, or backend service.
- Changing Ollama or provider/runtime selection behavior.
- Turning every nested form into a separate URL or browser page.

## Anti-goals

- A permanently wide sidebar that reduces the chat workspace below a useful size.
- Deeply nested menus that hide common destinations.
- Emoji, mixed icon sources, continuously animated controls, or decorative effects that reduce clarity or performance.
- Losing user-entered form data when navigating among destinations.
- Hiding active CLI work or benchmark progress merely because the user switches sections.

## Constraints

- The application is currently one server-rendered HTML document with plain JavaScript and CSS. The navigation must build on that system.
- Existing element IDs and event handlers should remain stable where practical to avoid regressions.
- Existing UI settings already persist theme and skill-panel state; sidebar preferences should extend that schema.
- Only the selected primary destination is visible, but its DOM remains mounted so form state, streamed output, terminal state, and in-progress tasks survive navigation.
- Existing shortcut behavior remains available. A shortcut that opens CLI, Context, Skills, or Settings also selects that sidebar destination and expands an overlay on narrow screens when needed.
- Sidebar interaction must be keyboard operable and expose current selection with semantic navigation attributes.

## Approaches Considered

### 1. Persistent collapsible navigation rail — selected

A resizable left sidebar controls primary destinations and expands Hardware into a shallow secondary list. Collapsed mode retains recognizable icons. This gives every global function a stable home and materially reduces page length without introducing routing machinery.

### 2. Expandable grouped side menu

Broader groups would expand into multiple nested entries. This scales to more future features but creates deeper navigation and extra clicks for the current feature set.

### 3. Scroll-to-section side menu

The side menu would keep the existing long page and scroll to collapsible panels. This is the smallest structural change but does not solve the page-size and cognitive-load problem.

The user selected approach 1 and approved the initial expanded/collapsed layout. The user selected the precision-outline icon system (visual option A).

## Information Architecture

The primary sidebar contains:

1. Chat
2. Live CLI
3. Context & Files
4. Skills
5. Hardware
6. Settings

Hardware exposes this secondary navigation when Hardware is selected:

1. Overview
2. Profiles & Optimization
3. Hardware & Runtimes
4. Model Compatibility
5. Optimized Model Search
6. Benchmarks
7. Results & History
8. LocalPerf Packages

Overview summarizes compatibility mode, active runtime, detected accelerators, current model, and existing probe/verification status. It does not create a new recommendation engine or infer a new "safest action"; any recommendation shown must already be produced by current compatibility and provider-selection logic.

Existing Hardware controls map to subsections as follows:

- **Overview:** current hardware status, telemetry summary, active model/runtime summary, and existing compatibility/probe status.
- **Profiles & Optimization:** optimization target, GPU/VRAM profile, advanced GPU layers, primary GPU, context, batch controls, Save Profile, Reset to Automatic, and Restore CPU.
- **Hardware & Runtimes:** Scan Again and the detected backend/runtime candidate list, including runtime installation, recheck, test, and use actions already rendered there.
- **Model Compatibility:** installed-model compatibility and acceleration status produced by current detection data.
- **Optimized Model Search:** provider selector, search query/action, pinned offline candidates, remote on-demand results, download, and probe actions.
- **Benchmarks:** suite, model, backend selectors, benchmark run action, active status, and the current/selected run result.
- **Results & History:** previous benchmark runs and Clear Benchmark Data.
- **LocalPerf Packages:** export-detail consent, selected-run export, package selection/import, imported-detail retention consent, and package status.

Control behavior and IDs remain unchanged unless an ID is tied exclusively to the retired two-tab control.

Settings becomes the home for general interface configuration and continues to own approved skill directories. The Skills destination keeps skill discovery and its scan-directory input; Settings does not duplicate or move those mounted controls. Hardware remains its own global destination because its size and operational role exceed a normal settings subsection.

## Layout and Interaction

### Expanded mode

- The sidebar starts at a practical default width of 260 CSS pixels.
- A visible divider/handle resizes it within a bounded range proposed as 220–380 pixels.
- Text labels and precision-outline icons are both visible.
- Hardware secondary navigation appears inline below Hardware while that destination is active.
- The selected destination and subsection use a strong, theme-aware active treatment.

### Collapsed mode

- The sidebar becomes a narrow icon rail proposed as 64–72 pixels.
- Each icon has an accessible name and a hover/focus tooltip.
- Selecting Hardware opens its secondary menu as a temporary flyout; the user may expand the full sidebar if they want the menu pinned.
- Collapsing does not change the selected destination.

### Narrow windows

- Below the existing responsive breakpoint, the sidebar becomes an overlay drawer and does not compress the main workspace.
- The drawer closes after selecting a destination and can be reopened with the global navigation control.
- The main workspace remains the only content in normal document flow while the drawer is closed.

### Resizing and persistence

- Pointer dragging updates width with `requestAnimationFrame`-bounded visual updates and does not continuously write settings.
- The final bounded width is persisted when dragging ends.
- Keyboard users can focus the separator and adjust it in fixed increments with arrow keys.
- The existing settings API stores sidebar collapsed state, width, and selected primary destination. The selected Hardware subsection is also stored so reopening Hardware returns the user to their last location.
- Invalid or legacy saved values fall back to defaults without blocking the interface.
- During legacy migration, `skill_catalog_open: true` selects Skills only when no new primary-destination value exists; otherwise the saved primary destination wins. Legacy users without either value start in Chat.

## Icons and Visual Treatment

- Use locally defined inline SVG symbols; do not add a package or remote asset request.
- All icons use a shared 24-pixel view box, consistent stroke weight, rounded line caps, and no filled decorative layers.
- Icons represent Chat, CLI, Context & Files, Skills, Hardware, and Settings.
- Icons inherit `currentColor`, support both themes, and never carry meaning without an accessible text label or tooltip.
- Resizing, collapse, and flyout transitions are brief and disabled under reduced-motion preferences. No continuous animations are introduced.

## State and Behavior

- Navigation changes visibility only. It does not recreate panels, clear form values, stop a terminal command, cancel inference, or discard benchmark results.
- In-progress destinations display a small static status indicator in the sidebar where useful, such as CLI running or benchmark running.
- Existing top-bar health status remains globally visible. The top bar is simplified after the four panel buttons move into navigation.
- Direct DOM focus moves to the selected destination heading after explicit keyboard navigation, but pointer navigation does not unexpectedly steal focus.
- Browser back/forward routing is not added in this revision; navigation is application state persisted through settings.

## Accessibility

- Use a semantic `nav` landmark and buttons with `aria-current` or equivalent selected-state semantics.
- The resize divider uses separator semantics, reports its current value, and supports keyboard adjustment.
- Collapsed icons retain accessible names independent of tooltips.
- The overlay traps focus while open and returns focus to its toggle when closed.
- Hidden destinations use the `hidden` attribute so assistive technology reads only the active workspace.
- Active colors meet contrast requirements in light and dark modes.

## Error Handling and Compatibility

- Failure to save layout preferences does not prevent navigation; the user receives the existing non-blocking error treatment and the session state continues locally.
- Missing settings fields are treated as legacy configuration.
- Hardware actions and results continue using current APIs. The refactor must not change the base Ollama path or optional provider probing.
- The current top-bar panel buttons may remain temporarily in markup during implementation only if hidden behind the new navigation, then should be removed once shortcut and accessibility behavior is verified.

## Verification

- Add focused tests for settings schema normalization and persistence of the new sidebar values.
- Extend existing static/UI tests to verify the navigation destinations, Hardware subsection mapping, and removal of the old Hardware two-tab structure.
- Verify JavaScript syntax and run the repository's focused Python tests affected by settings and UI structure.
- Perform an integrated browser pass in light and dark modes at wide and narrow sizes.
- Confirm CLI output, attachment state, skill editor state, active benchmark progress, and chat content survive switching destinations.

## Builder Decisions

The builder may choose exact CSS class names, small spacing values, the precise responsive breakpoint already consistent with the stylesheet, and the implementation structure for local SVG symbol reuse. The proposed width bounds may be adjusted slightly if the existing workspace minimum width requires it, provided the sidebar remains user-resizable and the chosen width persists.
