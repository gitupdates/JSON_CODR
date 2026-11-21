(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.JSONCodrNavigationRoutes = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function destinationFromSearch(search, allowedDestinations) {
    const destination = new URLSearchParams(search || "").get("view");
    return destination && allowedDestinations.has(destination) ? destination : null;
  }

  return { destinationFromSearch };
});
