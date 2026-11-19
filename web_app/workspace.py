import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from web_app.models import ChatMessage, SessionRecord


SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class InvalidSessionId(ValueError):
    pass


def default_data_root() -> Path:
    configured = os.environ.get("JSON_CODR_DATA_ROOT")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "JSON_CODR"


class WorkspaceService:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.sessions_root = self.data_root / "sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)

    def _validate_id(self, session_id: str) -> None:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise InvalidSessionId("Invalid session ID")

    def _session_directory(self, session_id: str) -> Path:
        self._validate_id(session_id)
        candidate = self.sessions_root / session_id
        if candidate.exists() and self._is_reparse_point(candidate):
            raise InvalidSessionId("Session workspace cannot be a reparse point")
        resolved = candidate.resolve()
        if self.sessions_root != resolved.parent:
            raise InvalidSessionId("Session workspace escapes the data root")
        return candidate

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        details = path.lstat()
        return path.is_symlink() or bool(
            getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )

    def create_session(self) -> SessionRecord:
        now = datetime.now(timezone.utc)
        record = SessionRecord(id=uuid.uuid4().hex, created_at=now, updated_at=now)
        self._session_directory(record.id).mkdir()
        self.save_manifest(record)
        return record

    def get_session(self, session_id: str) -> SessionRecord:
        manifest = self._session_directory(session_id) / "manifest.json"
        if not manifest.is_file():
            raise KeyError(session_id)
        with manifest.open("r", encoding="utf-8") as source:
            raw = json.load(source)
        record = SessionRecord.model_validate(raw)
        record.schema_version = 2
        if record.model_dump(mode="json") != raw:
            self.save_manifest(record)
        return record

    def append_message(self, session_id: str, message: ChatMessage) -> SessionRecord:
        record = self.get_session(session_id)
        record.messages.append(message)
        record.updated_at = datetime.now(timezone.utc)
        self.save_manifest(record)
        return record

    def delete_session(self, session_id: str) -> None:
        directory = self._session_directory(session_id)
        if not directory.is_dir():
            raise KeyError(session_id)
        shutil.rmtree(directory)

    def save_manifest(self, record: SessionRecord) -> None:
        directory = self._session_directory(record.id)
        if not directory.is_dir():
            raise KeyError(record.id)
        temporary = directory / "manifest.json.tmp"
        manifest = directory / "manifest.json"
        payload = record.model_dump(mode="json")
        with temporary.open("w", encoding="utf-8", newline="\n") as destination:
            json.dump(payload, destination, ensure_ascii=False, indent=2)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, manifest)

    def clear_skill_pack(self, pack_id: str) -> None:
        prefix = f"{pack_id}:"
        for directory in self.sessions_root.iterdir():
            if not directory.is_dir():
                continue
            try:
                record = self.get_session(directory.name)
            except (KeyError, InvalidSessionId, ValueError):
                continue
            selected = [item for item in record.selected_skill_ids if not item.startswith(prefix)]
            if selected != record.selected_skill_ids:
                record.selected_skill_ids = selected
                self.save_manifest(record)
