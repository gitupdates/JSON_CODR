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
      const persisted = parseStored(safeLoad(catalog.STORAGE_KEY));
      if (persisted && typeof persisted === "object" && persisted.schema === 1) {
        savedState = catalog.normalizeState(persisted);
      }
      snapshot = clone(savedState);
      draftState = clone(savedState);
      return applyDraft();
    }

    function selectPreset(preset) {
      if (!Object.hasOwn(catalog.PRESETS, preset)) return clone(draftState);
      const definition = catalog.PRESETS[preset];
      return replaceDraft({
        schema: 1,
        preset,
        mode: definition.defaultMode,
        density: definition.defaultDensity,
        typography: definition.defaultTypography,
        components: {},
      });
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
      if (catalog.PRESETS[draftState.preset].components[family] === variant) return resetComponent(family);
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

  function bindUICustomizationEditor({ controller, catalog, elements, confirmPresetChange }) {
    if (!controller || !catalog || !elements) throw new Error("Appearance editor requires controller, catalog, and elements");
    const confirmReplacement = confirmPresetChange || ((message) => globalThis.confirm ? globalThis.confirm(message) : true);

    function render() {
      const draft = controller.getDraft();
      const preset = catalog.PRESETS[draft.preset];
      elements.preset.innerHTML = optionsHtml(Object.entries(catalog.PRESETS).map(([id, value]) => [id, value.label]), draft.preset);
      elements.preset.value = draft.preset;
      elements.presetDetails.innerHTML = Object.entries(catalog.PRESETS).map(([presetId, value]) => {
        const color = value.colorCapability === "fixed" ? `Fixed ${value.fixedMode}` : `Adaptive · default ${value.defaultMode}`;
        const fonts = value.typographies.map((id) => catalog.TYPOGRAPHIES[id].label).join(", ");
        return `<button type="button" class="ui-preset-card" data-preset-choice="${escapeHtml(presetId)}" aria-pressed="${presetId === draft.preset}"><span class="preset-swatch" data-preset-swatch="${escapeHtml(presetId)}" aria-hidden="true"></span><span class="ui-preset-card-copy"><strong>${escapeHtml(value.label)}</strong><small>${escapeHtml(value.description)}</small><span class="ui-preset-meta">Color: ${escapeHtml(color)} · Density: ${escapeHtml(value.densities.join(", "))} · Font: ${escapeHtml(fonts)}</span></span></button>`;
      }).join("");
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
        return `<div class="ui-component-row"><label>${escapeHtml(definition.label)}<select class="setting-select" data-family="${escapeHtml(family)}">${optionsHtml(choices, selected)}</select></label><button class="secondary" type="button" data-reset-family="${escapeHtml(family)}">Use preset</button></div>`;
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

    function focusPresetCard(presetId) {
      elements.presetDetails.querySelector?.(`[data-preset-choice="${presetId}"]`)?.focus?.();
    }

    function choosePreset(presetId, restoreCardFocus = false) {
      const draft = controller.getDraft();
      const replacingOverrides = presetId !== draft.preset && Object.keys(draft.components).length > 0;
      if (replacingOverrides && !confirmReplacement("Changing preset will replace component overrides. Continue?")) {
        elements.status.textContent = "Preset change canceled";
        render();
        if (restoreCardFocus) focusPresetCard(draft.preset);
        return false;
      }
      preview(() => controller.selectPreset(presetId));
      if (restoreCardFocus) focusPresetCard(presetId);
      return true;
    }

    elements.preset.addEventListener("change", () => choosePreset(elements.preset.value));
    elements.presetDetails.addEventListener("click", (event) => {
      const choice = event.target?.closest?.("[data-preset-choice]") || event.target;
      const presetId = choice?.dataset?.presetChoice;
      if (presetId) choosePreset(presetId, true);
    });
    elements.mode.addEventListener("change", () => preview(() => controller.setMode(elements.mode.value)));
    elements.density.addEventListener("change", () => preview(() => controller.setDensity(elements.density.value)));
    elements.typography.addEventListener("change", () => preview(() => controller.setTypography(elements.typography.value)));
    elements.components.addEventListener("change", (event) => {
      const family = event.target?.dataset?.family;
      if (family) preview(() => controller.setComponent(family, event.target.value));
    });
    elements.components.addEventListener("click", (event) => {
      const family = event.target?.dataset?.resetFamily;
      if (family) preview(() => controller.resetComponent(family));
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
