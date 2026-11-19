(function (global) {
  class CoreClient {
    constructor({ fetchImpl = global.fetch.bind(global), WebSocketImpl = global.WebSocket } = {}) {
      this.fetch = fetchImpl;
      this.WebSocket = WebSocketImpl;
      this.tasks = new Map();
      this.listeners = new Set();
      this.socket = null;
    }

    subscribe(listener) {
      this.listeners.add(listener);
      return () => this.listeners.delete(listener);
    }

    async submit({ projectId, threadId, sessionId, model, prompt, projectRoot = ".", attachments = [] }) {
      const nonce = global.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const command = {
        schema_version: "1",
        command_id: `web-${nonce}`,
        task_id: `task-${nonce}`,
        thread_id: threadId,
        project_id: projectId,
        command_type: "capability.execute",
        payload: {
          capability_id: "inference.generate",
          operation: "generate",
          project_root: projectRoot,
          mode: "native",
          arguments: { model, prompt, session_id: sessionId, attachments, public_reasoning: true },
        },
      };
      return this.submitCommand(command);
    }

    async submitCommand(command) {
      const record = await this.request("/api/tasks/live", { method: "POST", body: command });
      this.tasks.set(record.task_id, { command, record });
      this.emit(record);
      this.observe(record.task_id, record.events.at(-1)?.sequence ?? -1);
      return record;
    }

    async steer(taskId, input) {
      const event = await this.request(`/api/tasks/${encodeURIComponent(taskId)}/steer`, {
        method: "POST", body: { input },
      });
      this.merge(taskId, [event]);
      return event;
    }

    async cancel(taskId) {
      const record = await this.request(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
      this.tasks.get(taskId).record = record;
      this.emit(record);
      return record;
    }

    async retry(taskId) {
      const previous = this.tasks.get(taskId)?.command;
      if (!previous) throw new Error("Task command is unavailable for retry");
      const nonce = global.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const command = { ...previous, command_id: `web-${nonce}`, task_id: `task-${nonce}`, parent_task_id: taskId };
      const record = await this.request(`/api/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST", body: command });
      this.tasks.set(record.task_id, { command, record });
      this.emit(record);
      this.observe(record.task_id, record.events.at(-1)?.sequence ?? -1);
      return record;
    }

    async restore(taskId, checkpointId) {
      return this.request(`/api/tasks/${encodeURIComponent(taskId)}/restore`, {
        method: "POST", body: { checkpoint_id: checkpointId },
      });
    }

    async planComponent(request) {
      return this.request("/api/components/plan", { method: "POST", body: request });
    }

    async installComponent(planId, approvedDigest) {
      return this.request(`/api/components/install/${encodeURIComponent(planId)}`, { method: "POST", body: { approved_digest: approvedDigest } });
    }

    async listComponents(projectId = "") {
      return this.request(`/api/components?project_id=${encodeURIComponent(projectId)}`);
    }

    observe(taskId, afterSequence = -1) {
      if (!this.WebSocket) return;
      if (!this.socket || this.socket.readyState > 1) {
        const scheme = global.location?.protocol === "https:" ? "wss" : "ws";
        const host = global.location?.host || "127.0.0.1:8772";
        this.socket = new this.WebSocket(`${scheme}://${host}/ws/tasks`);
        this.socket.addEventListener("message", (event) => {
          const payload = JSON.parse(event.data);
          if (payload.task_id && payload.events) this.merge(payload.task_id, payload.events);
        });
      }
      const send = () => this.socket.send(JSON.stringify({ task_id: taskId, after_sequence: afterSequence }));
      if (this.socket.readyState === 1) send();
      else this.socket.addEventListener("open", send, { once: true });
    }

    merge(taskId, events) {
      const state = this.tasks.get(taskId);
      if (!state) return;
      const bySequence = new Map(state.record.events.map((event) => [event.sequence, event]));
      events.forEach((event) => bySequence.set(event.sequence, event));
      const mergedEvents = [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
      const terminal = [...mergedEvents].reverse().find((event) => [
        "task.completed", "task.failed", "task.cancelled", "task.interrupted",
      ].includes(event.event_type));
      const status = terminal ? terminal.event_type.slice("task.".length) :
        (mergedEvents.some((event) => event.event_type === "task.started") ? "running" : state.record.status);
      state.record = { ...state.record, status, events: mergedEvents };
      this.emit(state.record);
    }

    emit(record) { this.listeners.forEach((listener) => listener(record)); }

    async request(url, { method = "GET", body } = {}) {
      const response = await this.fetch(url, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      const payload = await response.json();
      if (!response.ok && response.status !== 202) throw new Error(payload.detail || "JSON_CODR request failed");
      return payload;
    }
  }

  global.JSONCodrCoreClient = CoreClient;
  if (typeof module !== "undefined") module.exports = CoreClient;
})(typeof window !== "undefined" ? window : globalThis);
