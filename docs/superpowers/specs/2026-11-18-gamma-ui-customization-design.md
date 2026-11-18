# Gamma UI Customization Design

## Intent

Create a new `gamma/ui-customization` experience for JSON_CODR that adopts the strongest visual patterns from the supplied sanitized `UI.zip` archive without importing the unrelated NOCWatch or Acme Lookup application behavior. The Gamma interface must preserve every existing JSON_CODR workflow while letting a user select complete visual presets or customize individual component families. Developers must be able to change the mapping between a visual variant and a JSON_CODR component from one explicit catalog.

The redesign is intended for the same local JSON_CODR user. It should make the application feel more cohesive, information-dense, and operationally legible while retaining the current unified workspace, task controls, terminal, context, skills, hardware, settings, responsive layouts, and accessibility behavior.

## Goals

- Add a token-and-variant UI system layered over the existing stable DOM and behavior.
- Ship several curated, selectable presets built from imported visual ideas.
- Add an in-app Appearance editor for preset selection and per-component overrides.
- Keep component mappings developer-editable in one human-readable JavaScript catalog.
- Preview changes immediately and persist them locally.
- Preserve light, dark, responsive, keyboard, focus, and reduced-motion behavior.
- Reuse only appropriate sanitized assets from `UI.zip`, with licenses retained.
- Ensure invalid or obsolete saved customization data falls back safely.

## Non-goals

- Import NOCWatch business logic, network maps, device data, search behavior, charts, or vendor libraries.
- Rebuild JSON_CODR as a framework application or introduce a frontend build system.
- Replace stable element IDs, API contracts, task flows, or existing event wiring.
- Synchronize appearance settings between machines or users.
- Repair the existing Python 3.14 versus optional-runtime Python 3.11/3.12 architecture.
- Add arbitrary user-authored CSS or remote theme downloads.

## Anti-goals

- A theme implementation that duplicates the entire application stylesheet per preset.
- HTML template replacement that can silently detach existing event handlers.
- A component picker exposing internal selectors or requiring users to understand CSS.
- Importing sanitized legacy branding as JSON_CODR product identity.
- Visual density that makes controls harder to discover or use on narrow screens.

## Constraints

- The frontend remains vanilla HTML, CSS, and JavaScript served by the current FastAPI application.
- Existing Python installations are used as-is; UI work must not depend on runtime changes.
- Existing untracked files in the Alpha checkout are not part of the Gamma branch.
- The supplied archive is reference material plus a limited asset source, not application code to merge wholesale.
- All existing form labels, ARIA relationships, keyboard interactions, and stable IDs must remain functional.
- Appearance state is local-only and must work without network access.

## Approaches considered

### 1. Token-and-variant registry — selected

Define semantic design tokens, component-family variants, preset compositions, and JSON_CODR target mappings in one catalog. Apply the selected values through root data attributes and CSS custom properties. This preserves behavior, supports safe mixing, minimizes CSS duplication, and gives developers one mapping surface.

### 2. Independent stylesheet packs

Load a complete stylesheet for each preset and a second override stylesheet for mixed selections. This is initially simple but duplicates selectors, makes cross-theme fixes expensive, and produces unpredictable cascade interactions when components are mixed.

### 3. Replaceable HTML component templates

Use a registry that swaps markup as well as styles. This offers the most structural freedom but risks breaking the current event bindings, accessibility relationships, and large vanilla-JavaScript surface. It would turn a visual redesign into a frontend rewrite.

## Visual direction

Gamma combines JSON_CODR's local-agent identity with selected NOCWatch qualities:

- IBM Plex Sans for interface copy and IBM Plex Mono for code, metadata, model names, and terminal-adjacent labels.
- A disciplined application shell with a strong sidebar, compact top bar, clear active destination, and operational status indicators.
- Sharper panels and controls with restrained radii, visible borders, compact spacing, and clearer information hierarchy.
- Theme-specific accents and surface treatments without changing task semantics.
- Accessible typography option using the supplied OpenDyslexic files.
- No imported maps, network terminology, legacy brands, or dashboard content.

The default Gamma preset should feel intentional rather than decorative: dark graphite surfaces, a warm orange accent derived from the sanitized shell, compact navigation, and monospaced operational metadata. Existing JSON_CODR lime remains available in another preset.

## Theme presets

Ship these initial presets:

1. **Gamma Operations** — default Gamma look; graphite surfaces, warm orange accent, IBM Plex, compact shell, squared operational controls.
2. **JSON_CODR Classic** — preserves the current dark/light token identity and component shapes as the compatibility preset.
3. **NOC Light** — bright neutral surfaces, blue-orange operational accents, compact cards, strong dividers.
4. **Terminal Focus** — darker low-distraction surfaces, lime/cyan signals, mono-forward typography, dense controls.
5. **Accessible Read** — high-contrast surfaces, larger spacing and targets, OpenDyslexic body option, reduced decorative effects.

Each preset defines a color mode, token set, and one variant choice for every supported component family. Light/dark/system remains a separate preference where the preset supports both color modes; fixed-color presets disclose that they override the mode.

### Authoritative preset matrix

| Preset | Color capability | Default mode | Density | Typography | Component variants (`shell`, `navigation`, `topbar`, `panels`, `controls`, `tabs`, `composer`, `status`, `terminal`) |
| --- | --- | --- | --- | --- | --- |
| Gamma Operations | light/dark/system | dark | compact or comfortable; compact default | IBM Plex, system, or OpenDyslexic | operations, operations, operations, outlined, compact, underline, operations, signal, integrated |
| JSON_CODR Classic | light/dark/system | current saved mode, otherwise dark | comfortable or compact; comfortable default | system, IBM Plex, or OpenDyslexic | classic, classic, classic, glass, rounded, pill, classic, classic, classic |
| NOC Light | fixed light | light | compact or comfortable; compact default | IBM Plex, system, or OpenDyslexic | operations-light, rail, operations, flat, compact, segmented, operations, signal, integrated-light |
| Terminal Focus | fixed dark | dark | compact or comfortable; compact default | mono-forward, IBM Plex, or system | focus, rail, minimal, flat, terminal, underline, focus, terminal, focus |
| Accessible Read | light/dark/system | system | comfortable only | OpenDyslexic, system, or IBM Plex; OpenDyslexic default | accessible, high-contrast, high-contrast, high-contrast, accessible, high-contrast, accessible, high-contrast, accessible |

Fixed-color presets retain the user's saved adaptive `mode` without applying it. Switching back to an adaptive preset restores that saved mode. The editor disables the mode control for fixed presets and explains why.

OpenDyslexic always selects comfortable density. Selecting compact density while OpenDyslexic is active changes typography to the preset's non-accessibility default after confirmation. Accessible Read never permits compact density. All other listed typography/density combinations are valid.

## Component families and mappings

The first Gamma release supports these component families:

- `shell`: page background, ambient treatment, content width, and global density.
- `navigation`: sidebar, brand treatment, destination buttons, subnavigation, and collapse control.
- `topbar`: workspace title, health indicator, and mobile menu.
- `panels`: cards, docks, context surfaces, dialogs, and results.
- `controls`: buttons, inputs, selects, textareas, toggles, and focus treatment.
- `tabs`: task tabs, terminal tabs, and section tabs.
- `composer`: prompt entry, attachments, run/stop controls, and response surface.
- `status`: health, task state, approval, warning, error, and informational indicators.
- `terminal`: terminal frame and adjacent agent form; xterm's own color integration remains isolated.
- `typography`: interface font, mono font, size scale, and optional accessible font.

The authoritative variant inventory is:

| Family | Allowed variants |
| --- | --- |
| `shell` | `classic`, `operations`, `operations-light`, `focus`, `accessible` |
| `navigation` | `classic`, `operations`, `rail`, `high-contrast` |
| `topbar` | `classic`, `operations`, `minimal`, `high-contrast` |
| `panels` | `glass`, `outlined`, `flat`, `high-contrast` |
| `controls` | `rounded`, `compact`, `terminal`, `accessible` |
| `tabs` | `pill`, `underline`, `segmented`, `high-contrast` |
| `composer` | `classic`, `operations`, `focus`, `accessible` |
| `status` | `classic`, `signal`, `terminal`, `high-contrast` |
| `terminal` | `classic`, `integrated`, `integrated-light`, `focus`, `accessible` |
| `typography` | `system`, `ibm-plex`, `mono-forward`, `opendyslexic` |

Variant names and availability are catalog data. The editor shows the catalog's human labels and descriptions rather than these internal identifiers.

The developer catalog maps each family to stable target selectors and the allowed variants. A representative structure is:

```js
export const UI_COMPONENTS = {
  navigation: {
    label: "Navigation",
    targets: ["#app-sidebar", ".sidebar-destination", ".hardware-subnavigation"],
    variants: ["classic", "operations", "rail", "high-contrast"],
    defaultVariant: "operations",
  },
};
```

Selectors are metadata for developer orientation and validation; runtime styling is applied through semantic attributes such as `data-ui-navigation="operations"` on the document root. No code dynamically rewrites target HTML based on selector strings.

## Files and ownership

- `web/ui_catalog.js`: versioned preset definitions, component-family metadata, allowed variants, defaults, and migration helpers.
- `web/ui_customization.js`: state loading, validation, application, preview, persistence, reset, and editor event handling.
- `web/gamma.css`: semantic Gamma tokens plus component variant rules.
- `web/fonts/`: selected IBM Plex and OpenDyslexic files copied from the archive with license notices.
- `web/index.html`: minimal Appearance editor markup, stylesheet/script references, and stable semantic hooks where necessary.
- `web/app.js`: only integration hooks needed to open/refresh Appearance; theme ownership moves behind the customization module without changing other application behavior.
- `web_app/app.py`: static asset serving changes only if the existing `/static` mount does not already cover new files.

The catalog is the single developer-editable mapping source. CSS owns presentation. The customization module owns state. Existing feature modules continue to own application behavior.

## Appearance editor

Add an **Appearance** section under Settings with:

- Preset cards showing name, description, color character, density, and font.
- An immediate preview/apply action for each preset.
- An **Customize components** area with one labeled selector per supported family.
- A compact summary indicating which components differ from the active preset.
- **Reset component**, **Reset to preset**, and **Restore Gamma defaults** actions.
- An optional density choice (`comfortable`, `compact`) when supported by the selected preset.
- An optional typography choice (`IBM Plex`, `System`, `OpenDyslexic`) constrained by accessibility-safe combinations.

Changes apply immediately. The editor keeps a pre-edit snapshot while open so **Cancel** can restore the previous appearance. **Save appearance** persists the validated state. Preset selection clears component overrides only after an explicit confirmation when overrides exist.

The editor exposes human labels and small visual swatches, never raw selectors or CSS variable names.

## State model and persistence

Store one versioned object in local storage under `json_codr_ui_v1`:

```json
{
  "schema": 1,
  "preset": "gamma-operations",
  "mode": "dark",
  "density": "compact",
  "typography": "ibm-plex",
  "components": {
    "navigation": "operations",
    "panels": "outlined",
    "controls": "compact"
  }
}
```

On load, the catalog validator:

1. Rejects non-object or unsupported-schema data.
2. Resolves the preset or falls back to `gamma-operations`.
3. Filters component keys and variants against catalog allowlists.
4. Applies preset defaults, then valid overrides.
5. Preserves the existing `json_codr_theme` value by migrating it into `mode` on first load.
6. Writes corrected state only after explicit save, avoiding surprising persistence during recovery.

Migration precedence is deterministic: a valid `json_codr_ui_v1` object always wins when both keys exist. When only `json_codr_theme` exists, its valid `light`, `dark`, or `system` value seeds an in-memory Gamma state; repeated reloads may safely repeat this read-only migration until the user saves. The first explicit appearance save writes `json_codr_ui_v1` and deletes `json_codr_theme`. After that, only the versioned key is read or written. Invalid legacy values are ignored. Fixed-color presets store but temporarily override the migrated mode as described in the preset matrix.

The current theme bootstrap remains synchronous in the document head to avoid a flash of the wrong appearance. It reads only the small validated surface needed for first paint; the full module validates again after load.

## Rendering and interaction flow

```text
page load
  -> bootstrap reads saved appearance
  -> root receives preset/mode/family data attributes
  -> CSS renders before first paint
  -> customization module validates full state
  -> Settings editor reflects effective state

editor change
  -> update draft state
  -> validate against catalog
  -> apply root attributes immediately
  -> Save persists / Cancel restores snapshot
```

Application navigation, task execution, terminal, approvals, and responsive workspace logic do not pass through the customization module.

## Responsive behavior

- Existing workspace breakpoints and dock behavior remain authoritative.
- Component variants may change spacing, borders, and presentation but cannot change whether core regions exist.
- Sidebar variants collapse to the existing mobile drawer behavior.
- Preset cards become a single column on narrow screens.
- Customization selectors retain at least 44-pixel touch targets in comfortable mode and 36 pixels in compact desktop mode.
- The appearance editor itself must remain usable at 320 CSS pixels without horizontal scrolling.

## Accessibility

- Preserve semantic elements, labels, ARIA relationships, tab order, and visible focus.
- Every preset and supported component combination must meet WCAG AA contrast for normal text and essential controls.
- Color must not be the only indicator for task, health, warning, or error state.
- Respect `prefers-reduced-motion`; Gamma introduces no required motion.
- OpenDyslexic is optional, never silently enabled.
- Theme swatches have text labels and selected-state announcements.
- Preview/cancel changes are announced through a polite live region.

## Asset handling

Extract only the selected font files and their applicable license from `UI.zip`. Rename paths to JSON_CODR-owned static locations. Do not import archive JavaScript, network application HTML, map imagery, customer/device placeholders, third-party charting libraries, or old branding. Record source paths in a short asset notice so later maintainers can trace provenance.

The approved archive manifest is limited to:

- `UI/nocwatch/web/fonts/ibm-plex-sans.woff2`
- `UI/nocwatch/web/fonts/ibm-plex-mono-400.woff2`
- `UI/nocwatch/web/fonts/ibm-plex-mono-500.woff2`
- `UI/nocwatch/web/fonts/ibm-plex-mono-600.woff2`
- `UI/nocwatch/web/fonts/ibm-plex-mono-700.woff2`
- `UI/nocwatch/web/fonts/opendyslexic-400.woff2`
- `UI/nocwatch/web/fonts/opendyslexic-700.woff2`
- `UI/nocwatch/web/fonts/OpenDyslexic-OFL.txt`

The archive does not include an IBM Plex license file. The IBM Plex binaries must not be committed until the matching official license is added from an authoritative IBM Plex distribution and recorded in `web/fonts/THIRD_PARTY_NOTICES.md`. If that license cannot be obtained during implementation, Gamma uses the system font stack and ships OpenDyslexic only; missing IBM Plex is a graceful fallback, not a blocker. No duplicate copies under `refs/` or `ui-archive/` are imported.

## Error handling and compatibility

- Missing catalog entries use family defaults.
- Unknown persisted variants are ignored.
- A missing optional font falls back to the system font stack without blocking startup.
- If customization JavaScript fails, CSS defaults render the Gamma Operations preset and the app remains operable.
- Existing `json_codr_theme` values migrate once and continue to influence compatible presets.
- The Classic preset provides a visual rollback without changing branches.

## Testing and verification

Automated tests should cover:

- Catalog completeness: every preset supplies every required component family.
- Catalog validity: all referenced variants exist and selector metadata is non-empty.
- State parsing, filtering, migration, fallback, save, cancel, and reset behavior.
- First-paint bootstrap attributes for valid, invalid, and legacy state.
- Appearance editor controls, labels, persistence, override summaries, and confirmations.
- Existing navigation, workspace, settings, and static-asset tests remain unchanged or are updated only for intentional markup additions.
- Static checks ensure imported assets are limited to the approved list and license files exist.
- Responsive DOM/CSS assertions for mobile sidebar and settings layout.

Manual verification should exercise each preset at desktop, narrow, and mobile widths; keyboard-only operation; high zoom; reduced motion; terminal readability; task running/stopped/error states; and restart persistence. The known Python runtime discovery defect may prevent the existing server test suite from starting until a compatible optional-runtime interpreter is discoverable; it must be recorded separately and must not be “fixed” as part of Gamma UI work.

## Rollout

Gamma ships only on `gamma/ui-customization`. The default is Gamma Operations, with JSON_CODR Classic available as an immediate visual rollback. No Alpha data is rewritten beyond the local appearance key. The implementation should be reviewable in vertical slices: catalog/state engine, token/variant CSS, Appearance editor, imported assets, then regression/accessibility verification.

## Builder decisions left open

- Exact token values and final spacing measurements, provided they follow the approved visual direction and contrast constraints.
- Whether preset cards use CSS-only miniature previews or static swatches.
- Internal helper function names and module boundaries within the files listed above.
- The smallest set of existing CSS selectors that should be refactored to semantic variables rather than overridden.
