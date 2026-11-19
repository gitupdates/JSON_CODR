# Theme Settings Design

## Intent

Add a readable non-dark interface without removing JSON_CODR's existing dark appearance. Users choose Light, Dark, or System in Settings; the choice persists and System follows Windows appearance changes live.

## Goals

- Add Light, Dark, and System appearance choices to the existing Settings panel.
- Use the approved Indigo clarity light palette with strong text, border, control, and focus contrast.
- Preserve the current dark visual identity.
- Persist the selected mode through the existing Settings API.
- Apply the effective theme before normal application startup to minimize color flashing.
- Relaunch and verify the result in the internal browser.

## Non-goals and anti-goals

- No custom color picker or additional themes.
- No broad layout redesign.
- Do not reduce readability with pale text, color-only state indicators, or weak focus outlines.
- Do not make browser storage the source of truth for settings.

## Constraints

- The app currently uses a static HTML/CSS/JavaScript frontend and a Pydantic-backed settings API.
- Existing saved settings and unknown future configuration fields must remain compatible.
- System mode must respond to `prefers-color-scheme` changes without a reload.

## Approaches considered

1. **Persisted setting with an early startup cache — selected.** The Settings API remains authoritative. A local browser mirror supplies the last known mode before the API response, preventing an avoidable theme flash. This best matches the existing architecture and produces the smoothest startup.
2. **Browser-only preference.** Simpler, but it bypasses the settings service and does not follow the app's established persistence model.
3. **CSS-first switching.** Uses little JavaScript, but manual persistence and startup synchronization are less reliable.

## Design

- Extend `UiSettings` with a validated `theme` value: `light`, `dark`, or `system`, defaulting to `dark` to preserve existing behavior.
- Add an accessible radio-style theme selector to the Interface section of Settings.
- Set `data-theme` on the document to the effective `light` or `dark` theme. In System mode, derive it from `matchMedia('(prefers-color-scheme: dark)')` and listen for changes.
- Mirror the last saved mode in `localStorage` solely as an early-render cache; reconcile it with the API response during settings load.
- Convert hardcoded foregrounds, surfaces, borders, controls, focus rings, errors, and terminal colors into semantic CSS variables. Define the Indigo clarity values under the light-theme selector while retaining current values for dark mode.
- Update the document color-scheme metadata/property with the effective mode so native form controls render consistently.
- Apply a theme selection immediately, save it through `/api/settings`, and roll back to the previous mode if persistence fails.

## Verification

- Model and API tests cover the default, persistence, and accepted theme values.
- Static UI tests cover selector presence and theme application hooks.
