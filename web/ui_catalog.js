(function (root, factory) {
  const catalog = factory();
  if (typeof module === "object" && module.exports) module.exports = catalog;
  if (root) root.JSONCodrUICatalog = catalog;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const STORAGE_KEY = "json_codr_ui_v1";
  const LEGACY_THEME_KEY = "json_codr_theme";
  const MODES = Object.freeze(["light", "dark", "system"]);
  const DENSITIES = Object.freeze(["compact", "comfortable"]);
  const TYPOGRAPHIES = Object.freeze({
    system: { label: "System sans" },
    "mono-forward": { label: "Mono forward" },
    opendyslexic: { label: "OpenDyslexic" },
  });

  const COMPONENTS = deepFreeze({
    shell: { label: "Application shell", variants: ["classic", "operations", "operations-light", "focus", "accessible"] },
    navigation: { label: "Navigation", variants: ["classic", "operations", "rail", "high-contrast"] },
    topbar: { label: "Top bar", variants: ["classic", "operations", "minimal", "high-contrast"] },
    panels: { label: "Panels", variants: ["glass", "outlined", "flat", "high-contrast"] },
    controls: { label: "Controls", variants: ["rounded", "compact", "terminal", "accessible"] },
    tabs: { label: "Tabs", variants: ["pill", "underline", "segmented", "high-contrast"] },
    composer: { label: "Composer", variants: ["classic", "operations", "focus", "accessible"] },
    status: { label: "Status", variants: ["classic", "signal", "terminal", "high-contrast"] },
    terminal: { label: "Terminal", variants: ["classic", "integrated", "integrated-light", "focus", "accessible"] },
  });

  const PRESETS = deepFreeze({
    "gamma-operations": {
      label: "Gamma Operations",
      description: "Graphite operational surfaces with a warm orange signal color.",
      colorCapability: "adaptive",
      defaultMode: "dark",
      densities: ["compact", "comfortable"],
      defaultDensity: "compact",
      typographies: ["system", "opendyslexic"],
      defaultTypography: "system",
      components: {
        shell: "operations", navigation: "operations", topbar: "operations", panels: "outlined",
        controls: "compact", tabs: "underline", composer: "operations", status: "signal", terminal: "integrated",
      },
    },
    "json-codr-classic": {
      label: "JSON_CODR Classic",
      description: "The original JSON_CODR shapes, glass panels, and lime identity.",
      colorCapability: "adaptive",
      defaultMode: "dark",
      densities: ["comfortable", "compact"],
      defaultDensity: "comfortable",
      typographies: ["system", "opendyslexic"],
      defaultTypography: "system",
      components: {
        shell: "classic", navigation: "classic", topbar: "classic", panels: "glass",
        controls: "rounded", tabs: "pill", composer: "classic", status: "classic", terminal: "classic",
      },
    },
    "noc-light": {
      label: "NOC Light",
      description: "Bright operational surfaces, compact controls, and strong dividers.",
      colorCapability: "fixed",
      fixedMode: "light",
      defaultMode: "light",
      densities: ["compact", "comfortable"],
      defaultDensity: "compact",
      typographies: ["system", "opendyslexic"],
      defaultTypography: "system",
      components: {
        shell: "operations-light", navigation: "operations", topbar: "operations", panels: "flat",
        controls: "compact", tabs: "segmented", composer: "operations", status: "signal", terminal: "integrated-light",
      },
    },
    "terminal-focus": {
      label: "Terminal Focus",
      description: "Low-distraction dark surfaces with mono-forward controls.",
      colorCapability: "fixed",
      fixedMode: "dark",
      defaultMode: "dark",
      densities: ["compact", "comfortable"],
      defaultDensity: "compact",
      typographies: ["mono-forward", "system"],
      defaultTypography: "mono-forward",
      components: {
        shell: "focus", navigation: "rail", topbar: "minimal", panels: "flat",
        controls: "terminal", tabs: "underline", composer: "focus", status: "terminal", terminal: "focus",
      },
    },
    "accessible-read": {
      label: "Accessible Read",
      description: "High contrast, comfortable spacing, and optional accessible typography.",
      colorCapability: "adaptive",
      defaultMode: "system",
      densities: ["comfortable"],
      defaultDensity: "comfortable",
      typographies: ["opendyslexic", "system"],
      defaultTypography: "opendyslexic",
      components: {
        shell: "accessible", navigation: "high-contrast", topbar: "high-contrast", panels: "high-contrast",
        controls: "accessible", tabs: "high-contrast", composer: "accessible", status: "high-contrast", terminal: "accessible",
      },
    },
  });

  const DEFAULT_STATE = deepFreeze({
    schema: 1,
    preset: "noc-light",
    mode: "light",
    density: "compact",
    typography: "system",
    components: {},
  });

  function deepFreeze(value) {
    if (!value || typeof value !== "object" || Object.isFrozen(value)) return value;
    for (const child of Object.values(value)) deepFreeze(child);
    return Object.freeze(value);
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function validMode(value) {
    return MODES.includes(value);
  }

  function normalizeState(candidate, legacyMode) {
    const source = candidate && typeof candidate === "object" && candidate.schema === 1 ? candidate : {};
    const presetId = Object.hasOwn(PRESETS, source.preset) ? source.preset : DEFAULT_STATE.preset;
    const preset = PRESETS[presetId];
    const inheritedMode = validMode(legacyMode) ? legacyMode : preset.defaultMode;
    const mode = validMode(source.mode) ? source.mode : inheritedMode;
    let density = preset.densities.includes(source.density) ? source.density : preset.defaultDensity;
    const typography = preset.typographies.includes(source.typography) ? source.typography : preset.defaultTypography;
    if (typography === "opendyslexic" || presetId === "accessible-read") density = "comfortable";
    const components = {};
    if (source.components && typeof source.components === "object" && !Array.isArray(source.components)) {
      for (const [family, variant] of Object.entries(source.components)) {
        if (Object.hasOwn(COMPONENTS, family) && COMPONENTS[family].variants.includes(variant)) components[family] = variant;
      }
    }
    return { schema: 1, preset: presetId, mode, density, typography, components };
  }

  function effectiveState(candidate, systemDark = false) {
    const state = normalizeState(candidate);
    const preset = PRESETS[state.preset];
    const effectiveMode = preset.colorCapability === "fixed"
      ? preset.fixedMode
      : state.mode === "system" ? (systemDark ? "dark" : "light") : state.mode;
    return {
      ...clone(state),
      effectiveMode,
      components: { ...clone(preset.components), ...clone(state.components) },
    };
  }

  return deepFreeze({
    STORAGE_KEY,
    LEGACY_THEME_KEY,
    MODES,
    DENSITIES,
    TYPOGRAPHIES,
    COMPONENTS,
    PRESETS,
    DEFAULT_STATE,
    normalizeState,
    effectiveState,
  });
});
