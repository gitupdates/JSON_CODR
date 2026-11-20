import io
import json
import mimetypes
import re
import zipfile
from pathlib import Path

from web_app.artifacts import ArtifactService
from web_app.attachments import AttachmentService
from web_app.models import ChatMessage, ObjectReference
from web_app.workspace import WorkspaceService


class ConversationService:
    def __init__(
        self,
        workspace: WorkspaceService,
        attachments: AttachmentService,
        project_root: Path,
        artifacts: ArtifactService | None = None,
    ) -> None:
        self.workspace = workspace
        self.attachments = attachments
        self.project_root = Path(project_root).absolute()
        self.artifacts = artifacts or ArtifactService(workspace)

    def history(self, session_id: str) -> list[ChatMessage]:
        return list(self.workspace.get_session(session_id).messages)

    def append(self, session_id: str, message: ChatMessage) -> ChatMessage:
        self.workspace.append_message(session_id, message)
        return message

    def export_message(self, session_id: str, message_id: str, format: str) -> tuple[bytes, str, str]:
        message = next(
            (item for item in self.history(session_id) if item.id == message_id),
            None,
        )
        if message is None:
            raise KeyError(message_id)
        stem = f"json-codr-message-{message.id}"
        if format == "json":
            return (
                json.dumps(message.model_dump(mode="json"), ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json",
                f"{stem}.json",
            )
        if format == "markdown":
            return self._message_markdown(message).encode("utf-8"), "text/markdown", f"{stem}.md"
        raise ValueError("Unsupported conversation export format")

    def export_session(
        self,
        session_id: str,
        format: str,
        *,
        include_binaries: bool = False,
    ) -> tuple[bytes, str, str]:
        session = self.workspace.get_session(session_id)
        payload = session.model_dump(mode="json")
        stem = f"json-codr-conversation-{session.id}"
        json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        markdown = self._session_markdown(session.messages).encode("utf-8")
        if format == "json":
            return json_bytes, "application/json", f"{stem}.json"
        if format == "markdown":
            return markdown, "text/markdown", f"{stem}.md"
        if format != "zip":
            raise ValueError("Unsupported conversation export format")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("conversation.json", json_bytes)
            archive.writestr("conversation.md", markdown)
            if include_binaries:
                for record in session.attachments:
                    try:
                        path, _ = self.attachments.original_path(session_id, record.id)
                    except KeyError:
                        continue
                    archive.writestr(f"attachments/{self._archive_name(record.display_name)}", path.read_bytes())
        return output.getvalue(), "application/zip", f"{stem}.zip"

    def resolve_reference(
        self,
        session_id: str,
        reference: ObjectReference,
    ) -> tuple[Path, str]:
        self.workspace.get_session(session_id)
        if reference.kind == "attachment":
            path, record = self.attachments.original_path(session_id, reference.target)
            return path, record.detected_type or "application/octet-stream"
        if reference.kind == "artifact":
            path = self.artifacts.artifact_path(session_id, reference.target)
            return path, mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if reference.kind == "project_file":
            candidate = self.project_root / reference.target
            resolved_root = self.project_root.resolve()
            resolved_candidate = candidate.resolve()
            if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
                raise PermissionError("Project reference escapes the active project")
            if not resolved_candidate.is_file():
                raise KeyError(reference.target)
            return candidate, mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        raise ValueError("Reference kind does not resolve to a local file")

    def find_reference(self, session_id: str, reference_id: str) -> ObjectReference:
        for message in self.history(session_id):
            for reference in message.references:
                if reference.id == reference_id:
                    return reference
        raise KeyError(reference_id)

    @staticmethod
    def _message_markdown(message: ChatMessage) -> str:
        parts = [f"## {message.role.title()}", "", message.content]
        if message.task_id:
            parts.extend(["", f"Task: `{message.task_id}`"])
        if message.reasoning and message.reasoning.entries:
            parts.extend(["", "### Public reasoning trace", ""])
            parts.extend(
                f"- **{entry.kind}** ({entry.provenance}): {entry.text}"
                for entry in message.reasoning.entries
            )
        return "\n".join(parts).rstrip() + "\n"

    def _session_markdown(self, messages: list[ChatMessage]) -> str:
        sections = ["# JSON_CODR conversation", ""]
        for message in messages:
            sections.append(self._message_markdown(message))
        return "\n".join(sections).rstrip() + "\n"

    @staticmethod
    def _archive_name(value: str) -> str:
        name = Path(value.replace("\\", "/")).name
        return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or "attachment"
