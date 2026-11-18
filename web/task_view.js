(function (global) {
  function createTaskView(elements, client = null) {
    let activeTaskId = null;
    let currentPlan = null;
    let refreshGeneration = 0;

    function render(record) {
      activeTaskId = record.task_id;
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
        if (event.event_type === "task.permission_required") {
          item.className = "permission-required";
          item.title = event.payload.strong_confirmation ? "Strong confirmation required" : "Approval required";
        }
      }
      elements.requested.textContent = requested;
      elements.effective.textContent = effective;
      elements.details.hidden = !(record.events || []).length;
      elements.stop.disabled = !["pending", "running", "cancel_requested"].includes(record.status);
      elements.retry.disabled = !["failed", "cancelled", "interrupted"].includes(record.status);
      const phase = taskPhase(record);
      renderPhase(phase);
      renderChanges(record);
      if (client && ["plan_review", "executing", "verifying", "delivering", "completed"].includes(phase)) {
        refreshPlan(record.task_id);
      }
      if (client && ["delivering", "completed", "failed"].includes(phase)) refreshDelivery(record.task_id);
    }

    function taskPhase(record) {
      const changed = [...(record.events || [])].reverse().find(event => event.event_type === "agent.phase_changed");
      if (changed?.payload?.phase) return changed.payload.phase;
      if (["completed", "failed", "cancelled"].includes(record.status)) return record.status;
      return "describe";
    }

    function renderPhase(phase) {
      const order = ["describe", "plan_review", "executing", "delivering"];
      const normalized = phase === "planning" ? "describe" : phase === "verifying" ? "executing" : phase === "completed" ? "delivering" : phase;
      const active = Math.max(0, order.indexOf(normalized));
      (elements.phases || []).forEach((node, index) => {
        if (index === active) node.setAttribute("aria-current", "step");
        else node.removeAttribute("aria-current");
        node.classList.toggle("is-complete", index < active);
      });
      if (elements.announcer) elements.announcer.textContent = `Task phase: ${normalized.replaceAll("_", " ")}`;
    }

    async function refreshPlan(taskId) {
      const generation = ++refreshGeneration;
      try {
        const plans = await client.listPlans(taskId);
        if (generation !== refreshGeneration || !plans.length) return;
        currentPlan = plans.at(-1);
        renderPlan(currentPlan, plans);
      } catch (error) {
        announce(error.message);
      }
    }

    function renderPlan(plan, history) {
      if (!elements.planSummary) return;
      elements.planSummary.textContent = plan.summary || `Revision ${plan.revision}`;
      elements.planPolicy.textContent = `${plan.review_status.replaceAll("_", " ")} · revision ${plan.revision}`;
      elements.planSteps.replaceChildren(...plan.steps.map(stepCard));
      const list = elements.revisionHistory?.querySelector("ol");
      if (list) {
        list.replaceChildren(...history.map(item => {
          const row = document.createElement("li");
          row.textContent = `Revision history · ${item.revision}: ${item.revision_reason || item.summary || "Initial plan"}`;
          return row;
        }));
      }
    }

    function stepCard(step) {
      const card = document.createElement("article");
      card.className = "task-plan-step";
      card.dataset.stepId = step.step_id;
      const heading = document.createElement("h3");
      heading.textContent = step.title || step.step_id;
      const purpose = document.createElement("p");
      purpose.textContent = step.purpose || `${step.capability_id} · ${step.operation}`;
      const badge = document.createElement("span");
      badge.className = "task-effect-badge";
      badge.textContent = step.effect_class === "destructive" ? "Strong confirmation" : step.effect_class.replaceAll("_", " ");
      const actions = document.createElement("div");
      actions.className = "task-review-actions";
      for (const [label, action] of [["Approve step", "approve"], ["Edit step", "edit"], ["Reject step", "reject"]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = action === "approve" ? "primary" : "secondary";
        button.dataset.stepAction = action;
        button.dataset.stepId = step.step_id;
        button.textContent = label;
        actions.append(button);
      }
      card.append(heading, purpose, badge, actions);
      return card;
    }

    function renderChanges(record) {
      if (!elements.changeList) return;
      const completed = (record.events || []).filter(event => event.event_type === "agent.action_completed");
      elements.changeList.replaceChildren(...(completed.length ? completed.map(event => {
        const item = document.createElement("li");
        item.textContent = `${event.payload.step_id || "Step"} completed`;
        return item;
      }) : [Object.assign(document.createElement("li"), { textContent: "No approved steps have executed." })]));
    }

    async function refreshDelivery(taskId) {
      try {
        const delivery = await client.taskDelivery(taskId);
        elements.verificationSummary.textContent = delivery.verification?.report_id
          ? `Verified by ${delivery.verification.report_id}`
          : (delivery.warnings || []).join(" · ") || "Verification has not completed.";
        elements.artifacts.replaceChildren(...(delivery.artifacts || []).map(artifact => {
          const card = document.createElement("a");
          card.className = "task-artifact-card";
          card.href = artifact.download_url;
          card.textContent = `Download ${artifact.media_type} · ${artifact.size} bytes`;
          return card;
        }));
      } catch (error) {
        announce(error.message);
      }
    }

    async function runReview(action) {
      if (!activeTaskId || !currentPlan) return;
      try {
        await action();
        announce("Review saved");
        await refreshPlan(activeTaskId);
      } catch (error) {
        if (error.status === 409 && error.current_digest) {
          announce("Plan changed in another view. Refreshing the current revision.");
          await refreshPlan(activeTaskId);
          return;
        }
        announce(error.message);
      }
    }

    function announce(message) {
      if (elements.announcer) elements.announcer.textContent = message;
    }

    function eventLabel(event) {
      if (event.event_type === "inference.completed") return event.payload.result?.summary || "Model response completed";
      if (event.event_type === "inference.content.delta") return "Response streaming";
      if (event.event_type === "inference.reasoning.delta") return `Public reasoning · ${event.payload.provenance || "provider"}`;
      if (event.event_type === "inference.warning") return event.payload.message || "Inference warning";
      return event.event_type.replaceAll(".", " ");
    }

    (elements.tabs || []).forEach(tab => tab.addEventListener("click", () => {
      (elements.tabs || []).forEach(item => item.setAttribute("aria-selected", String(item === tab)));
      (elements.panels || []).forEach(panel => { panel.hidden = panel.dataset.taskPanel !== tab.dataset.taskTab; });
    }));
    elements.planApprove?.addEventListener("click", () => runReview(() => client.approvePlan(activeTaskId, currentPlan)));
    elements.planReject?.addEventListener("click", () => {
      const reason = global.prompt?.("Why should this plan be rejected?");
      if (reason) runReview(() => client.rejectPlan(activeTaskId, currentPlan, reason));
    });
    elements.planRevise?.addEventListener("click", () => {
      const summary = global.prompt?.("Revised plan summary", currentPlan?.summary || "");
      const reason = summary && global.prompt?.("Reason for this revision");
      if (summary && reason) runReview(() => client.revisePlan(activeTaskId, currentPlan, summary, reason));
    });
    elements.planSteps?.addEventListener("click", event => {
      const action = event.target.dataset.stepAction;
      const stepId = event.target.dataset.stepId;
      if (!action || !stepId) return;
      if (action === "approve") runReview(() => client.approveStep(activeTaskId, currentPlan, stepId));
      if (action === "reject") {
        const reason = global.prompt?.("Why should this step be rejected?");
        if (reason) runReview(() => client.rejectStep(activeTaskId, currentPlan, stepId, reason));
      }
      if (action === "edit") {
        const step = currentPlan.steps.find(item => item.step_id === stepId);
        const title = global.prompt?.("Step title", step?.title || "");
        if (title !== null && title !== undefined) runReview(() => client.editStep(activeTaskId, currentPlan, stepId, { title }));
      }
    });

    return { render, refreshPlan, refreshDelivery };
  }

  global.JSONCodrTaskView = createTaskView;
  if (typeof module !== "undefined") module.exports = createTaskView;
})(typeof window !== "undefined" ? window : globalThis);
