(function (global) {
  function createTaskView(elements) {
    function render(record) {
      elements.activity.replaceChildren();
      let requested = "Not reported";
      let effective = "Not reported";
      for (const event of record.events || []) {
        const item = document.createElement("li");
        item.dataset.eventType = event.event_type;
        item.textContent = eventLabel(event);
        elements.activity.append(item);
        if (event.event_type === "inference.completed") {
          requested = event.payload.requested_model_id || requested;
          effective = event.payload.effective_model_id || effective;
        }
        if (event.event_type === "task.permission_required") item.className = "permission-required";
      }
      elements.requested.textContent = requested;
      elements.effective.textContent = effective;
      elements.details.hidden = !(record.events || []).length;
      elements.stop.disabled = !["pending", "running", "cancel_requested"].includes(record.status);
      elements.retry.disabled = !["failed", "cancelled", "interrupted"].includes(record.status);
    }

    function eventLabel(event) {
      if (event.event_type === "inference.completed") {
        return event.payload.result?.summary || "Model response completed";
      }
      if (event.event_type === "inference.content.delta") return "Response streaming";
      if (event.event_type === "inference.reasoning.delta") {
        return `Public reasoning · ${event.payload.provenance || "provider"}`;
      }
      if (event.event_type === "inference.warning") return event.payload.message || "Inference warning";
      return event.event_type.replaceAll(".", " ");
    }
    return { render };
  }

  global.JSONCodrTaskView = createTaskView;
  if (typeof module !== "undefined") module.exports = createTaskView;
})(typeof window !== "undefined" ? window : globalThis);
