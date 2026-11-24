(function (global) {
  class ConversationView {
    constructor({ timeline = null, fetchImpl = global.fetch?.bind(global) } = {}) {
      this.timeline = timeline;
      this.fetch = fetchImpl;
      this.messages = [];
      this.taskMessages = new Map();
      this.sequences = new Map();
      this.sessionId = null;
    }

    snapshot() {
      return JSON.parse(JSON.stringify(this.messages));
    }

    async restore(sessionId) {
      this.sessionId = sessionId;
      const response = await this.fetch(`/api/sessions/${encodeURIComponent(sessionId)}/conversation`);
      if (!response.ok) throw new Error("Unable to restore conversation");
      this.restoreMessages(await response.json());
    }

    restoreMessages(messages) {
      this.messages = (messages || []).map((message) => this.normalizeMessage(message));
      this.render();
    }

    async appendUser(content, attachmentIds = []) {
      const message = this.normalizeMessage({
        id: this.id(), role: "user", content, status: "completed", attachment_ids: attachmentIds,
      });
      this.messages.push(message);
      this.render();
      await this.persist(message);
      return message;
    }

    beginTask(taskId, { requestedModel = null, parentMessageId = null } = {}) {
      const message = this.normalizeMessage({
        id: this.id(), role: "assistant", content: "", status: "streaming",
        task_id: taskId, requested_model: requestedModel, parent_message_id: parentMessageId,
      });
      this.messages.push(message);
      this.taskMessages.set(taskId, message);
      this.sequences.set(taskId, new Set());
      this.render();
      return message;
    }

    apply(record) {
      const message = this.taskMessages.get(record.task_id);
      if (!message) return null;
      const seen = this.sequences.get(record.task_id) || new Set();
      for (const event of record.events || []) {
        if (seen.has(event.sequence)) continue;
        seen.add(event.sequence);
        this.applyEvent(message, event);
      }
      this.sequences.set(record.task_id, seen);
      if (["failed", "cancelled", "interrupted"].includes(record.status) && message.status === "streaming") {
        message.status = message.content ? "incomplete" : "failed";
      }
      this.render();
      return message;
    }

    applyEvent(message, event) {
      const payload = event.payload || {};
      if (event.event_type === "inference.content.delta") message.content += payload.text || "";
      if (event.event_type === "inference.reasoning.delta") {
        message.reasoning.entries.push({
          sequence: event.sequence, kind: "analysis", text: payload.text || "",
          provenance: payload.provenance || "native_provider",
        });
      }
      if (event.event_type === "inference.reference") message.references.push(payload);
      if (event.event_type === "inference.warning") message.reasoning.warnings.push(payload.message || "Inference warning");
      if (event.event_type === "inference.completed") {
        const result = payload.result || {};
        message.content = result.content || message.content;
        message.status = "completed";
        message.effective_model = payload.effective_model_id || result.model || message.requested_model;
        if (result.reasoning) message.reasoning = result.reasoning;
        if (result.references) message.references = result.references;
        if (result.artifact?.filename) {
          message.references.push({
            id: `artifact-${result.artifact.filename}`,
            kind: "artifact",
            label: result.artifact.filename,
            target: result.artifact.filename,
            available: true,
          });
        }
        message.result = result;
      }
      if (["task.failed", "task.cancelled", "task.interrupted"].includes(event.event_type)) {
        message.status = message.content ? "incomplete" : "failed";
        message.error = payload.reason || payload.message || event.event_type.replaceAll(".", " ");
      }
    }

    async persistCompleted(taskId) {
      const message = this.taskMessages.get(taskId);
      if (!message || message.persisted || !["completed", "incomplete", "failed"].includes(message.status)) return;
      message.persisted = true;
      await this.persist(message);
    }

    async persist(message) {
      if (!this.sessionId || !this.fetch) return;
      const payload = { ...message };
      delete payload.result;
      delete payload.error;
      delete payload.persisted;
      const baseHeaders = { "Content-Type": "application/json" };
      const headers = global.JSONCodrHttpIdentity?.mutationHeaders
        ? global.JSONCodrHttpIdentity.mutationHeaders(baseHeaders)
        : baseHeaders;
      const response = await this.fetch(
        `/api/sessions/${encodeURIComponent(this.sessionId)}/conversation`,
        { method: "POST", headers, body: JSON.stringify(payload) },
      );
      if (!response.ok) throw new Error("Unable to save conversation message");
    }

    normalizeMessage(message) {
      return {
        id: message.id || this.id(), role: message.role || "assistant", content: message.content || "",
        status: message.status || "completed", task_id: message.task_id || null,
        requested_model: message.requested_model || null, effective_model: message.effective_model || null,
        parent_message_id: message.parent_message_id || null,
        attachment_ids: message.attachment_ids || [], artifacts: message.artifacts || [],
        references: message.references || [],
        reasoning: message.reasoning || { schema_version: 1, entries: [], warnings: [] },
        created_at: message.created_at || new Date().toISOString(),
        updated_at: message.updated_at || new Date().toISOString(),
      };
    }

    render() {
      if (!this.timeline || typeof document === "undefined") return;
      this.timeline.replaceChildren();
      for (const message of this.messages) this.timeline.append(this.renderMessage(message));
      this.timeline.scrollTop = this.timeline.scrollHeight;
    }

    renderMessage(message) {
      const article = document.createElement("article");
      article.className = `conversation-message ${message.role}`;
      article.dataset.messageId = message.id;
      const header = document.createElement("header");
      const role = document.createElement("strong"); role.textContent = message.role === "user" ? "You" : (message.effective_model || message.requested_model || "Model");
      const status = document.createElement("span"); status.textContent = message.status;
      header.append(role, status); article.append(header);
      const content = document.createElement("pre"); content.textContent = message.content || (message.status === "streaming" ? "Waiting for the first response…" : ""); article.append(content);
      if (message.reasoning.entries.length || message.reasoning.warnings.length) {
        const details = document.createElement("details"); details.className = "reasoning-trace";
        const summary = document.createElement("summary"); summary.textContent = "Public reasoning trace"; details.append(summary);
        for (const entry of message.reasoning.entries) {
          const row = document.createElement("p"); row.textContent = `${entry.kind} · ${entry.provenance}: ${entry.text}`; details.append(row);
        }
        for (const warning of message.reasoning.warnings) {
          const row = document.createElement("p"); row.className = "reasoning-warning"; row.textContent = warning; details.append(row);
        }
        article.append(details);
      }
      if (message.references.length) {
        const references = document.createElement("nav"); references.className = "message-references"; references.setAttribute("aria-label", "Referenced objects");
        for (const reference of message.references) {
          const link = document.createElement("a");
          link.textContent = reference.label || reference.id;
          link.href = `/api/sessions/${encodeURIComponent(this.sessionId)}/references/${encodeURIComponent(reference.id)}`;
          link.download = ""; references.append(link);
        }
        article.append(references);
      }
      if (message.attachment_ids.length && this.sessionId) {
        const attachments = document.createElement("nav"); attachments.className = "message-references"; attachments.setAttribute("aria-label", "Message attachments");
        for (const attachmentId of message.attachment_ids) {
          const link = document.createElement("a"); link.textContent = `Attachment ${attachmentId.slice(0, 8)}`;
          link.href = `/api/sessions/${encodeURIComponent(this.sessionId)}/attachments/${encodeURIComponent(attachmentId)}/original`;
          link.download = ""; attachments.append(link);
        }
        article.append(attachments);
      }
      if (this.sessionId && message.id) {
        const exports = document.createElement("div"); exports.className = "message-exports";
        for (const format of ["markdown", "json"]) {
          const link = document.createElement("a"); link.textContent = `Export ${format}`;
          link.href = `/api/sessions/${encodeURIComponent(this.sessionId)}/messages/${encodeURIComponent(message.id)}/export?format=${format}`;
          link.download = ""; exports.append(link);
        }
        article.append(exports);
      }
      if (message.error) {
        const error = document.createElement("p"); error.className = "message-error"; error.textContent = message.error; article.append(error);
      }
      return article;
    }

    id() {
      const value = global.crypto?.randomUUID?.() || `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
      return value.replaceAll("-", "").padEnd(32, "0").slice(0, 32);
    }
  }

  global.JSONCodrConversationView = ConversationView;
  if (typeof module !== "undefined") module.exports = ConversationView;
})(typeof window !== "undefined" ? window : globalThis);
