(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) {
    root.JSONCodrDisclosures = api;
    if (root.document) api.bindExclusiveDisclosures(root.document);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function closeAll(document, except = null) {
    for (const detail of document.querySelectorAll("details[open]")) {
      if (detail !== except) detail.open = false;
    }
  }

  function bindExclusiveDisclosures(document) {
    if (!document || document.__jsonCodrDisclosureBinding) return;
    document.__jsonCodrDisclosureBinding = true;
    document.addEventListener("toggle", event => {
      const detail = event.target;
      if (detail && detail.open === true) closeAll(document, detail);
    }, true);
    document.addEventListener("click", event => {
      if (event.target?.closest?.(".sidebar-destination")) closeAll(document);
    });
  }

  return {bindExclusiveDisclosures, closeAll};
});
