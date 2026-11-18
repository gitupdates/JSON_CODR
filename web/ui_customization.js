(function (root, factory) {
  const createUICustomizationController = factory();
  if (typeof module === "object" && module.exports) module.exports = createUICustomizationController;
  if (root) root.createUICustomizationController = createUICustomizationController;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function parseStored(value) {
    if (typeof value !== "string") return value;
    try { return JSON.parse(value); } catch (_error) { return null; }
  }

  return function createUICustomizationController(options = {}) {
    const catalog = options.catalog || globalThis.JSONCodrUICatalog;
    if (!catalog) throw new Error("JSONCodrUICatalog is required");
    const load = options.load || ((key) => {
      const value = localStorage.getItem(key);
      return key === catalog.LEGACY_THEME_KEY ? value : parseStored(value);
    });
    const saveValue = options.save || ((key, value) => localStorage.setItem(key, JSON.stringify(value)));
    const removeLegacy = options.removeLegacy || ((key) => globalThis.localStorage?.removeItem(key));
    const apply = options.apply || (() => {});
    const announce = options.announce || (() => {});
    const systemDark = options.systemDark === undefined
      ? () => globalThis.matchMedia?.("(prefers-color-scheme: dark)").matches === true
      : typeof options.systemDark === "function" ? options.systemDark : () => options.systemDark === true;

    function safeLoad(key) {
      try { return load(key); } catch (_error) { return null; }
    }

    const stored = parseStored(safeLoad(catalog.STORAGE_KEY));
    const legacyMode = safeLoad(catalog.LEGACY_THEME_KEY);
    let savedState = catalog.normalizeState(stored, legacyMode);
    let draftState = clone(savedState);
    let snapshot = null;

    function effective(state = draftState) {
      return catalog.effectiveState(state, systemDark());
    }

    function applyDraft() {
      const value = effective();
      apply(clone(value));
      return clone(draftState);
    }

    function replaceDraft(candidate) {
      draftState = catalog.normalizeState(candidate);
      return applyDraft();
    }

    function begin() {
      snapshot = clone(savedState);
      draftState = clone(savedState);
      return applyDraft();
    }

    function selectPreset(preset) {
      if (!Object.hasOwn(catalog.PRESETS, preset)) return clone(draftState);
      return replaceDraft({ schema: 1, preset, mode: draftState.mode, components: {} });
    }

    function setMode(mode) {
      if (!catalog.MODES.includes(mode)) return clone(draftState);
      return replaceDraft({ ...draftState, mode });
    }

    function setDensity(density) {
      if (!catalog.DENSITIES.includes(density)) return clone(draftState);
      return replaceDraft({ ...draftState, density });
    }

    function setTypography(typography) {
      if (!Object.hasOwn(catalog.TYPOGRAPHIES, typography)) return clone(draftState);
      return replaceDraft({ ...draftState, typography });
    }

    function setComponent(family, variant) {
      const definition = catalog.COMPONENTS[family];
      if (!definition || !definition.variants.includes(variant)) return clone(draftState);
      return replaceDraft({
        ...draftState,
        components: { ...draftState.components, [family]: variant },
      });
    }

    function resetComponent(family) {
      if (!Object.hasOwn(catalog.COMPONENTS, family)) return clone(draftState);
      const components = { ...draftState.components };
      delete components[family];
      return replaceDraft({ ...draftState, components });
    }

    function resetPreset() {
      return selectPreset(draftState.preset);
    }

    function save() {
      savedState = catalog.normalizeState(draftState);
      draftState = clone(savedState);
      snapshot = clone(savedState);
      saveValue(catalog.STORAGE_KEY, clone(savedState));
      removeLegacy(catalog.LEGACY_THEME_KEY);
      applyDraft();
      announce("Appearance saved");
      return clone(savedState);
    }

    function cancel() {
      draftState = clone(snapshot || savedState);
      applyDraft();
      announce("Appearance preview canceled");
      return clone(draftState);
    }

    return Object.freeze({
      getState: () => clone(savedState),
      getDraft: () => clone(draftState),
      getEffectiveState: () => clone(effective()),
      begin,
      selectPreset,
      setMode,
      setDensity,
      setTypography,
      setComponent,
      resetComponent,
      resetPreset,
      save,
      cancel,
    });
  };
});
