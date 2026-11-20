(function (root, factory) {
  const createWorkspaceLayoutController = factory();
  if (typeof module === "object" && module.exports) module.exports = createWorkspaceLayoutController;
  if (root) root.createWorkspaceLayoutController = createWorkspaceLayoutController;
})(typeof window !== "undefined" ? window : globalThis, function () {
  const REGIONS = ["left", "right", "bottom"];
  const STORAGE_KEY = "json_codr_workspace_layout_v1";
  const DEFAULT_BOUNDS = {
    left: { min: 180, max: 420, default: 260 },
    right: { min: 200, max: 480, default: 300 },
    bottom: { min: 140, max: 600, default: 260 },
  };
  const DEFAULT_PLACEMENTS = { files: "left", activity: "right", terminal: "bottom" };

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  return function createWorkspaceLayoutController(options = {}) {
    const available = new Set(Array.isArray(options.availablePanels) ? options.availablePanels : []);
    const placements = options.panelPlacements || {};
    const bounds = Object.fromEntries(REGIONS.map((region) => {
      const supplied = options.bounds?.[region] || {};
      const fallback = DEFAULT_BOUNDS[region];
      return [region, {
        min: Number.isFinite(supplied.min) ? supplied.min : fallback.min,
        max: Number.isFinite(supplied.max) ? supplied.max : fallback.max,
        default: Number.isFinite(supplied.default) ? supplied.default : fallback.default,
      }];
    }));
    const load = options.load || (() => {
      try { return JSON.parse(localStorage.getItem(STORAGE_KEY)); } catch (_error) { return null; }
    });
    const save = options.save || ((value) => localStorage.setItem(STORAGE_KEY, JSON.stringify(value)));
    let wideRegions = null;

    function allowed(panel, region) {
      return available.has(panel) && REGIONS.includes(region) && (placements[panel] || []).includes(region);
    }

    function defaults() {
      const regions = { left: [], right: [], bottom: [] };
      for (const [panel, region] of Object.entries(DEFAULT_PLACEMENTS)) {
        if (allowed(panel, region)) regions[region].push(panel);
      }
      return {
        version: 1,
        mode: "wide",
        desktopRegions: null,
        regions,
        sizes: Object.fromEntries(REGIONS.map((region) => [region, bounds[region].default])),
        collapsed: { left: false, right: false, bottom: false },
        focusedPanel: regions.bottom.at(-1) || regions.right.at(-1) || regions.left.at(-1) || null,
        preset: "default",
      };
    }

    function normalize(candidate) {
      if (!candidate || candidate.version !== 1) return defaults();
      const next = defaults();
      const seen = new Set();
      for (const region of REGIONS) {
        next.regions[region] = [];
        const panels = Array.isArray(candidate.regions?.[region]) ? candidate.regions[region] : [];
        for (const panel of panels) {
          if (!seen.has(panel) && allowed(panel, region)) {
            next.regions[region].push(panel);
            seen.add(panel);
          }
        }
        const size = candidate.sizes?.[region];
        if (Number.isFinite(size)) next.sizes[region] = Math.max(bounds[region].min, Math.min(bounds[region].max, size));
        next.collapsed[region] = candidate.collapsed?.[region] === true;
      }
      for (const [panel, region] of Object.entries(DEFAULT_PLACEMENTS)) {
        if (!seen.has(panel) && allowed(panel, region)) next.regions[region].push(panel);
      }
      const visible = REGIONS.flatMap((region) => next.regions[region]);
      next.focusedPanel = visible.includes(candidate.focusedPanel) ? candidate.focusedPanel : (visible.at(-1) || null);
      next.preset = ["default", "focus", "code", "observe"].includes(candidate.preset) ? candidate.preset : "default";
      next.mode = ["wide", "intermediate", "narrow", "mobile"].includes(candidate.mode) ? candidate.mode : "wide";
      if (candidate.desktopRegions && typeof candidate.desktopRegions === "object") {
        const desktopRegions = { left: [], right: [], bottom: [] };
        const desktopSeen = new Set();
        for (const region of REGIONS) {
          const panels = Array.isArray(candidate.desktopRegions[region]) ? candidate.desktopRegions[region] : [];
          for (const panel of panels) {
            if (!desktopSeen.has(panel) && allowed(panel, region)) {
              desktopRegions[region].push(panel);
              desktopSeen.add(panel);
            }
          }
        }
        if (desktopSeen.size) next.desktopRegions = desktopRegions;
      }
      return next;
    }

    let state;
    try { state = normalize(load()); } catch (_error) { state = defaults(); }

    function persist() {
      try { save(clone(state)); } catch (_error) { /* Layout storage is best-effort. */ }
    }

    function remove(panel) {
      for (const region of REGIONS) state.regions[region] = state.regions[region].filter((item) => item !== panel);
    }

    function getState() { return clone(state); }

    function open(panel, region) {
      if (!available.has(panel)) return getState();
      const existing = REGIONS.find((item) => state.regions[item].includes(panel));
      const destination = allowed(panel, region) ? region : existing || (placements[panel] || [])[0];
      if (!allowed(panel, destination)) return getState();
      if (existing !== destination) {
        remove(panel);
        state.regions[destination].push(panel);
      }
      state.focusedPanel = panel;
      state.collapsed[destination] = false;
      persist();
      return getState();
    }

    function focus(panel) {
      if (REGIONS.some((region) => state.regions[region].includes(panel))) {
        state.focusedPanel = panel;
        persist();
      }
      return getState();
    }

    function move(panel, region) { return open(panel, region); }

    function collapse(region, value) {
      if (REGIONS.includes(region)) {
        state.collapsed[region] = Boolean(value);
        persist();
      }
      return getState();
    }

    function resize(region, value) {
      if (REGIONS.includes(region) && Number.isFinite(value)) {
        state.sizes[region] = Math.max(bounds[region].min, Math.min(bounds[region].max, value));
        persist();
      }
      return getState();
    }

    function close(panel) {
      remove(panel);
      const visible = REGIONS.flatMap((region) => state.regions[region]);
      if (state.focusedPanel === panel) state.focusedPanel = visible.at(-1) || null;
      persist();
      return getState();
    }

    function ensure(panel, region) {
      if (!available.has(panel) || !allowed(panel, region)) return;
      remove(panel);
      state.regions[region].push(panel);
    }

    function applyPreset(name) {
      if (name === "focus") state.collapsed = { left: true, right: true, bottom: true };
      else if (name === "code") {
        ensure("files", "left");
        ensure("terminal", "bottom");
        state.regions.left = state.regions.left.filter((panel) => panel === "files");
        state.regions.bottom = state.regions.bottom.filter((panel) => panel === "terminal");
        state.collapsed = { left: false, right: true, bottom: false };
      } else if (name === "observe") {
        ensure("activity", "right");
        ensure("output", "bottom");
        state.regions.right = state.regions.right.filter((panel) => panel === "activity");
        state.regions.bottom = state.regions.bottom.filter((panel) => panel === "output");
        state.collapsed = { left: true, right: false, bottom: false };
      } else return getState();
      state.preset = name;
      persist();
      return getState();
    }

    function applyViewport(width) {
      if (!Number.isFinite(width)) return getState();
      const mode = width >= 1200 ? "wide" : width >= 900 ? "intermediate" : width >= 600 ? "narrow" : "mobile";
      if (mode === "wide") {
        const desktopRegions = wideRegions || state.desktopRegions;
        if (desktopRegions) {
          state.regions = clone(desktopRegions);
          wideRegions = null;
        }
        state.desktopRegions = null;
      } else {
        if (!wideRegions) wideRegions = clone(state.desktopRegions || state.regions);
        state.desktopRegions = clone(wideRegions);
        const source = clone(wideRegions);
        if (mode === "intermediate") {
          const migrated = source.right.filter((panel) => allowed(panel, "bottom"));
          state.regions = { left: source.left, right: [], bottom: [...source.bottom, ...migrated] };
        } else {
          const ordered = REGIONS.flatMap((region) => source[region]);
          state.regions = { left: [], right: [], bottom: ordered.filter((panel) => allowed(panel, "bottom")) };
        }
      }
      state.mode = mode;
      const visible = REGIONS.flatMap((region) => state.regions[region]);
      if (!visible.includes(state.focusedPanel)) state.focusedPanel = visible.at(-1) || null;
      persist();
      return getState();
    }

    function reset() {
      state = defaults();
      wideRegions = null;
      persist();
      return getState();
    }

    return { getState, open, focus, move, collapse, resize, close, applyViewport, applyPreset, reset };
  };
});
