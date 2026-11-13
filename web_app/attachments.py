import hashlib
import os
import uuid
from pathlib import Path, PurePath
from typing import BinaryIO

from web_app.extraction import ExtractionService
from web_app.models import AttachmentRecord, ExtractionState
from web_app.workspace import WorkspaceService


class AttachmentTooLarge(ValueError):
    pass


class AttachmentService:
    def __init__(
        self,
        workspace: WorkspaceService,
        extraction: ExtractionService | None = None,
        max_file_bytes: int = 25 * 1024 * 1024,
        max_files: int = 25,
        max_session_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        self.workspace = workspace
        self.extraction = extraction or ExtractionService()
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.max_session_bytes = max_session_bytes

    @staticmethod
    def _display_name(value: str) -> str:
        normalized = value.replace("\\", "/")
        return PurePath(normalized).name or "attachment"

    def import_stream(self, session_id: str, display_name: str, stream: BinaryIO) -> AttachmentRecord:
        session = self.workspace.get_session(session_id)
        attachment_id = uuid.uuid4().hex
        safe_name = self._display_name(display_name)
        if len(session.attachments) >= self.max_files:
            raise AttachmentTooLarge(f"Session is limited to {self.max_files} attachments")
        data = stream.read(self.max_file_bytes + 1)
        if len(data) > self.max_file_bytes:
            record = AttachmentRecord(
                id=attachment_id,
                display_name=safe_name,
                size=len(data),
                extraction_state=ExtractionState.rejected,
                included=False,
                warnings=[f"File exceeds the {self.max_file_bytes}-byte limit"],
            )
            session.attachments.append(record)
            self.workspace.save_manifest(session)
            raise AttachmentTooLarge(record.warnings[0])
        used_bytes = sum(item.size for item in session.attachments if item.digest)
        if used_bytes + len(data) > self.max_session_bytes:
            record = AttachmentRecord(
                id=attachment_id,
                display_name=safe_name,
                size=len(data),
                extraction_state=ExtractionState.rejected,
                included=False,
                warnings=[f"Session exceeds the {self.max_session_bytes}-byte limit"],
            )
            session.attachments.append(record)
            self.workspace.save_manifest(session)
            raise AttachmentTooLarge(record.warnings[0])

        digest = hashlib.sha256(data).hexdigest()
        session_directory = self.workspace.sessions_root / session_id
        originals = session_directory / "originals"
        extracted = session_directory / "extracted"
        originals.mkdir(exist_ok=True)
        extracted.mkdir(exist_ok=True)
        storage_name = digest
        original_path = originals / storage_name
        if not original_path.exists():
            temporary = originals / f".{storage_name}.tmp"
            temporary.write_bytes(data)
            os.replace(temporary, original_path)
        detected_type = self._detected_type(safe_name)
        record = AttachmentRecord(
            id=attachment_id,
            display_name=safe_name,
            detected_type=detected_type,
            size=len(data),
            digest=digest,
            storage_name=storage_name,
            extracted_name=f"{attachment_id}.txt",
        )
        try:
            result = self.extraction.extract(original_path, record.detected_type)
            (extracted / record.extracted_name).write_text(result.text, encoding="utf-8")
            record.extraction_state = ExtractionState.ready
            record.warnings = result.warnings
        except ValueError as error:
            record.extraction_state = ExtractionState.rejected
            record.included = False
            record.warnings = [str(error)]
        session.attachments.append(record)
        self.workspace.save_manifest(session)
        return record

    @staticmethod
    def _detected_type(display_name: str) -> str:
        suffix = Path(display_name).suffix.lower()
        if suffix == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if suffix == ".pdf":
            return "application/pdf"
        if suffix == ".rtf":
            return "application/rtf"
        image_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        if suffix in image_types:
            return image_types[suffix]
        return "text/plain"

    def import_text(self, session_id: str, text: str, display_name: str = "Pasted text") -> AttachmentRecord:
        from io import BytesIO

        return self.import_stream(session_id, display_name, BytesIO(text.encode("utf-8")))

    def set_included(self, session_id: str, attachment_id: str, included: bool) -> AttachmentRecord:
        session = self.workspace.get_session(session_id)
        record = self._find(session.attachments, attachment_id)
        record.included = included
        self.workspace.save_manifest(session)
        return record

    def preview(self, session_id: str, attachment_id: str) -> dict[str, str]:
        session = self.workspace.get_session(session_id)
        record = self._find(session.attachments, attachment_id)
        if not record.extracted_name:
            return {"text": ""}
        path = self.workspace.sessions_root / session_id / "extracted" / record.extracted_name
        return {"text": path.read_text(encoding="utf-8")}

    def remove(self, session_id: str, attachment_id: str) -> None:
        session = self.workspace.get_session(session_id)
        record = self._find(session.attachments, attachment_id)
        session.attachments.remove(record)
        session_directory = self.workspace.sessions_root / session_id
        if record.extracted_name:
            (session_directory / "extracted" / record.extracted_name).unlink(missing_ok=True)
        if record.storage_name and not any(item.storage_name == record.storage_name for item in session.attachments):
            (session_directory / "originals" / record.storage_name).unlink(missing_ok=True)
        self.workspace.save_manifest(session)

    @staticmethod
    def _find(records: list[AttachmentRecord], attachment_id: str) -> AttachmentRecord:
        for record in records:
            if record.id == attachment_id:
                return record
        raise KeyError(attachment_id)
