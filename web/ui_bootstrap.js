(function (root, factory) {
  const bootstrapUI = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = bootstrapUI;
  } else {
    root.JSONCODRBootstrapUI = bootstrapUI;
    if (root.JSONCODRUICatalog && root.document) bootstrapUI();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function read(storage, key) {
    try {
      return storage && storage.getItem ? storage.getItem(key) : null;
    } catch (_error) {
      return null;
    }
  }

  function bootstrapUI(options) {
    options = options || {};
    const catalog = options.catalog || globalThis.JSONCODRUICatalog;
    const storage = options.storage || globalThis.localStorage;
    const root = options.root || globalThis.document.documentElement;
    if (!catalog || !root) return null;

    const raw = read(storage, catalog.STORAGE_KEY);
    let stored = null;
    if (raw) {
      try {
        stored = typeof raw === "string" ? JSON.parse(raw) : raw;
      } catch (_error) {
        stored = null;
      }
    }
    const legacyMode = read(storage, catalog.LEGACY_THEME_KEY);
    const state = catalog.normalizeState(stored, legacyMode);
    const systemDark = typeof options.systemDark === "function"
      ? options.systemDark()
      : typeof options.systemDark === "boolean"
        ? options.systemDark
        : Boolean(globalThis.matchMedia && globalThis.matchMedia("(prefers-color-scheme: dark)").matches);
    const effective = catalog.effectiveState(state, systemDark);

    root.dataset.theme = effective.effectiveMode;
    root.style.colorScheme = effective.effectiveMode;
    root.dataset.uiPreset = effective.preset;
    root.dataset.uiDensity = effective.density;
    root.dataset.uiTypography = effective.typography;
    for (const [family, variant] of Object.entries(effective.components)) {
      root.dataset[`ui${family.charAt(0).toUpperCase()}${family.slice(1)}`] = variant;
    }
    return effective;
  }

  return bootstrapUI;
});
