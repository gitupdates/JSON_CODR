import json
import os
import uuid
from pathlib import Path

from web_app.models import SettingsUpdate, SystemSettings


class SettingsService:
    def __init__(self, data_root: Path) -> None:
        self.path = Path(data_root).resolve() / "settings.json"

    def _raw(self) -> dict:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def get(self) -> SystemSettings:
        return SystemSettings.model_validate(self._raw())

    def update(self, update: SettingsUpdate) -> SystemSettings:
        raw = self._raw()
        current = self.get()
        if update.ui is not None:
            current.ui = update.ui
        if update.skill_scan is not None:
            resolved = []
            for value in update.skill_scan.approved_directories:
                path = str(Path(value).resolve())
                if path not in resolved:
                    resolved.append(path)
            current.skill_scan.approved_directories = resolved
        raw.update(current.model_dump(mode="json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / f".settings-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        return current
