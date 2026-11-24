(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.JSONCodrSourceNavigation = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function bindSourceNavigation(options = {}) {
    const document = options.document || globalThis.document;
    const window = options.window || globalThis.window;
    const sidebar = document.getElementById("app-sidebar");
    const collapse = document.getElementById("sidebar-collapse");
    const resizeHandle = document.getElementById("sidebar-resize-handle");
    const mobileToggle = document.getElementById("mobile-navigation-toggle");
    const backdrop = document.getElementById("navigation-backdrop");
    const narrowNavigation = window.matchMedia("(max-width: 700px)");
    const persist = options.persist || (async update => {
      const response = await fetch("/api/settings", {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ui: update}),
      });
      if (!response.ok) throw new Error("Unable to save navigation settings");
    });

    const boundedSidebarWidth = value => Math.max(220, Math.min(380, Number(value) || 260));

    function applySidebarWidth(value) {
      const width = boundedSidebarWidth(value);
      document.documentElement.style.setProperty("--sidebar-width", `${width}px`);
      resizeHandle.setAttribute("aria-valuenow", String(width));
      return width;
    }

    function closeNavigationDrawer({restoreFocus = false} = {}) {
      document.body.classList.remove("navigation-open");
      backdrop.hidden = true;
      mobileToggle.setAttribute("aria-expanded", "false");
      if (restoreFocus) mobileToggle.focus();
    }

    function openNavigationDrawer() {
      document.body.classList.add("navigation-open");
      backdrop.hidden = false;
      mobileToggle.setAttribute("aria-expanded", "true");
    }

    function setSidebarCollapsed(collapsed, {persist: shouldPersist = true} = {}) {
      document.body.classList.toggle("sidebar-collapsed", collapsed);
      collapse.setAttribute("aria-expanded", String(!collapsed));
      collapse.setAttribute("aria-label", collapsed ? "Expand navigation" : "Collapse navigation");
      if (shouldPersist) persist({sidebar_collapsed: collapsed}).catch(() => undefined);
    }

    async function hydrate() {
      const response = await fetch("/api/settings");
      if (!response.ok) return;
      const settings = await response.json();
      applySidebarWidth(settings.ui?.sidebar_width);
      setSidebarCollapsed(Boolean(settings.ui?.sidebar_collapsed), {persist: false});
    }

    collapse.addEventListener("click", () => {
      setSidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
    });
    mobileToggle.addEventListener("click", () => {
      if (document.body.classList.contains("navigation-open")) closeNavigationDrawer({restoreFocus: true});
      else openNavigationDrawer();
    });
    backdrop.addEventListener("click", () => closeNavigationDrawer({restoreFocus: true}));
    for (const link of document.querySelectorAll?.(".sidebar-destination") || []) {
      link.addEventListener("click", () => closeNavigationDrawer());
    }
    document.addEventListener?.("keydown", event => {
      if (event.key === "Escape" && document.body.classList.contains("navigation-open")) {
        closeNavigationDrawer({restoreFocus: true});
      }
    });

    resizeHandle.addEventListener("pointerdown", event => {
      if (narrowNavigation.matches) return;
      event.preventDefault();
      let pendingWidth = boundedSidebarWidth(event.clientX);
      let frame = null;
      const render = () => { frame = null; applySidebarWidth(pendingWidth); };
      const move = moveEvent => {
        pendingWidth = boundedSidebarWidth(moveEvent.clientX);
        if (frame === null) frame = window.requestAnimationFrame(render);
      };
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        const width = applySidebarWidth(pendingWidth);
        persist({sidebar_width: width}).catch(() => undefined);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    });
    resizeHandle.addEventListener("keydown", event => {
      const delta = event.key === "ArrowLeft" ? -10 : event.key === "ArrowRight" ? 10 : 0;
      if (!delta) return;
      event.preventDefault();
      const width = applySidebarWidth(Number(resizeHandle.attrs?.["aria-valuenow"] || resizeHandle.getAttribute?.("aria-valuenow")) + delta);
      persist({sidebar_width: width}).catch(() => undefined);
    });

    return {applySidebarWidth, closeNavigationDrawer, hydrate, openNavigationDrawer, setSidebarCollapsed};
  }

  return {bindSourceNavigation};
});

if (globalThis.document) {
  const controller = globalThis.JSONCodrSourceNavigation.bindSourceNavigation();
  controller.hydrate().catch(() => undefined);
}
