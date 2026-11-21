(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.JSONCodrSourceUpdates = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  async function checkAndMaybeUpdate({check, update, isCurrent = () => true, setBusy = () => {}}) {
    setBusy(true);
    try {
      const checked = await check();
      if (!checked) return {status: "cancelled", result: null, checked: null};
      if (!isCurrent()) return {status: "stale", result: null, checked};
      if (!checked.update_allowed) return {status: "checked", result: checked, checked};
      const updated = await update(checked);
      if (!updated) return {status: "checked", result: checked, checked};
      if (!isCurrent()) return {status: "stale", result: null, checked};
      return {status: "updated", result: updated, checked};
    } finally {
      setBusy(false);
    }
  }

  function checkBuild(request, scope) {
    return request("/api/github/local/check-build", {
      method: "POST",
      body: JSON.stringify({...scope, confirmed: true}),
    });
  }

  return {checkAndMaybeUpdate, checkBuild};
});
