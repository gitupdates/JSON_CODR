(function (global) {
  function bindAutoAttachControl({
    control,
    sessionId,
    fetchImpl = global.fetch,
    preview,
    showError,
  }) {
    control.addEventListener("change", async () => {
      const activeSessionId = typeof sessionId === "function" ? sessionId() : sessionId;
      const response = await fetchImpl(`/api/sessions/${activeSessionId}/skill-routing`, {
        method: "PATCH",
        headers: global.JSONCodrHttpIdentity.mutationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ auto_attach_skills: control.checked }),
      });
      if (!response.ok) {
        const payload = await response.json();
        showError(payload.detail || "Unable to update automatic attachment");
        return;
      }
      await preview();
    });
  }

  const api = { bindAutoAttachControl };
  global.JSONCodrSkillRouting = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
