(function (root, factory) {
  const createUICustomizationController = factory();
  if (typeof module === "object" && module.exports) module.exports = createUICustomizationController;
  if (root) {
    root.createUICustomizationController = createUICustomizationController;
    root.bindUICustomizationEditor = createUICustomizationController.bindUICustomizationEditor;
  }
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function parseStored(value) {
    if (typeof value !== "string") return value;
    try { return JSON.parse(value); } catch (_error) { return null; }
  }

  function createUICustomizationController(options = {}) {
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
    const hasVersionedState = Boolean(stored && typeof stored === "object" && stored.schema === 1);
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

    function restoreDefaults() {
      return replaceDraft(catalog.DEFAULT_STATE);
    }

    function seedLegacyMode(mode) {
      if (hasVersionedState || !catalog.MODES.includes(mode)) return clone(savedState);
      savedState = catalog.normalizeState({ ...savedState, mode });
      draftState = clone(savedState);
      snapshot = clone(savedState);
      return applyDraft();
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
      restoreDefaults,
      seedLegacyMode,
      save,
      cancel,
    });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  function optionsHtml(entries, selected) {
    return entries.map(([value, label]) =>
      `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`,
    ).join("");
  }

  function bindUICustomizationEditor({ controller, catalog, elements }) {
    if (!controller || !catalog || !elements) throw new Error("Appearance editor requires controller, catalog, and elements");

    function render() {
      const draft = controller.getDraft();
      const preset = catalog.PRESETS[draft.preset];
      elements.preset.innerHTML = optionsHtml(Object.entries(catalog.PRESETS).map(([id, value]) => [id, value.label]), draft.preset);
      elements.preset.value = draft.preset;
      elements.mode.innerHTML = optionsHtml(catalog.MODES.map((mode) => [mode, mode[0].toUpperCase() + mode.slice(1)]), draft.mode);
      elements.mode.value = draft.mode;
      elements.mode.disabled = preset.colorCapability === "fixed";
      elements.modeHelp.textContent = preset.colorCapability === "fixed"
        ? `${preset.label} uses fixed ${preset.fixedMode} colors.`
        : "System follows your Windows appearance.";
      elements.density.innerHTML = optionsHtml(preset.densities.map((value) => [value, value[0].toUpperCase() + value.slice(1)]), draft.density);
      elements.density.value = draft.density;
      elements.typography.innerHTML = optionsHtml(preset.typographies.map((value) => [value, catalog.TYPOGRAPHIES[value].label]), draft.typography);
      elements.typography.value = draft.typography;
      elements.components.innerHTML = Object.entries(catalog.COMPONENTS).map(([family, definition]) => {
        const selected = draft.components[family] || preset.components[family];
        const choices = definition.variants.map((variant) => [variant, variant.replaceAll("-", " ")]);
        return `<label class="ui-component-row">${escapeHtml(definition.label)}<select class="setting-select" data-family="${escapeHtml(family)}">${optionsHtml(choices, selected)}</select></label>`;
      }).join("");
      const count = Object.keys(draft.components).length;
      elements.summary.textContent = count === 1 ? "1 override" : `${count} overrides`;
      return draft;
    }

    function preview(mutator) {
      mutator();
      elements.status.textContent = "Previewing unsaved appearance";
      return render();
    }

    elements.preset.addEventListener("change", () => preview(() => controller.selectPreset(elements.preset.value)));
    elements.mode.addEventListener("change", () => preview(() => controller.setMode(elements.mode.value)));
    elements.density.addEventListener("change", () => preview(() => controller.setDensity(elements.density.value)));
    elements.typography.addEventListener("change", () => preview(() => controller.setTypography(elements.typography.value)));
    elements.components.addEventListener("change", (event) => {
      const family = event.target?.dataset?.family;
      if (family) preview(() => controller.setComponent(family, event.target.value));
    });
    elements.save.addEventListener("click", () => { controller.save(); elements.status.textContent = "Appearance saved"; render(); });
    elements.cancel.addEventListener("click", () => { controller.cancel(); elements.status.textContent = "Appearance preview canceled"; render(); });
    elements.resetPreset.addEventListener("click", () => preview(() => controller.resetPreset()));
    elements.restoreDefaults.addEventListener("click", () => preview(() => controller.restoreDefaults()));

    function begin() {
      controller.begin();
      elements.status.textContent = "Appearance controls ready";
      return render();
    }

    begin();
    return Object.freeze({ begin, render });
  }

  createUICustomizationController.bindUICustomizationEditor = bindUICustomizationEditor;
  return createUICustomizationController;
});
