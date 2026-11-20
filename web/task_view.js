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
        if (event.event_type === "inference.completed" || event.payload?.requested_model_id || event.payload?.effective_model_id) {
          requested = event.payload.requested_model_id || requested;
          effective = event.payload.effective_model_id || effective;
        }
        if (["task.permission_required", "agent.approval_required"].includes(event.event_type)) item.className = "permission-required";
      }
      elements.requested.textContent = requested;
      elements.effective.textContent = effective;
      elements.details.hidden = !(record.events || []).length;
      elements.stop.disabled = !["pending", "running", "cancel_requested"].includes(record.status);
      elements.retry.disabled = !["failed", "cancelled", "interrupted"].includes(record.status);
    }

    function eventLabel(event) {
      const payload = event.payload || {};
      const evidence = [];
      const execution_route = payload.execution_route || payload.route;
      const primitive_id = payload.primitive_id;
      const adapter_id = payload.adapter_id;
      const approval_state = payload.approval_state;
      const verification_status = payload.verification_status;
      const retry_count = payload.retry_count;
      const rollback_status = payload.rollback_status;
      const requested_model_id = payload.requested_model_id;
      const effective_model_id = payload.effective_model_id;
      if (execution_route) evidence.push(execution_route);
      if (primitive_id || adapter_id) evidence.push(primitive_id || adapter_id);
      if (requested_model_id || effective_model_id) evidence.push(`${requested_model_id || "not reported"} → ${effective_model_id || "not reported"}`);
      if (approval_state) evidence.push(`approval ${approval_state}`);
      if (verification_status) evidence.push(`verified ${verification_status}`);
      if (retry_count != null) evidence.push(`retries ${retry_count}`);
      if (rollback_status) evidence.push(`rollback ${rollback_status}`);
      const recommended_action = payload.recommended_action;
      if (recommended_action) evidence.push(`next: ${recommended_action}`);
      if (event.event_type.includes("repair")) evidence.push("staged repair");
      if (event.event_type === "inference.completed") {
        const summary = payload.result?.summary || "Model response completed";
        return evidence.length ? `${summary} · ${evidence.join(" · ")}` : summary;
      }
      if (event.event_type === "inference.content.delta") return "Response streaming";
      if (event.event_type === "inference.reasoning.delta") {
        return `Public reasoning · ${event.payload.provenance || "provider"}`;
      }
      if (event.event_type === "inference.warning") return event.payload.message || "Inference warning";
      const base = payload.message || event.event_type.replaceAll(".", " ");
      return evidence.length ? `${base} · ${evidence.join(" · ")}` : base;
    }
    return { render };
  }

  global.JSONCodrTaskView = createTaskView;
  if (typeof module !== "undefined") module.exports = createTaskView;
})(typeof window !== "undefined" ? window : globalThis);
