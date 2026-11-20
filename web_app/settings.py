import json
import os
import uuid
from pathlib import Path

from cli import load_config
from web_app.models import AutonomousCodingSettings, DesignerSettings, GpuOptimizationSettings, GpuProfileSettings, SettingsUpdate, SkillRoutingSettings, SystemSettings, UiSettings
from web_app.version import APP_VERSION


class SettingsService:
    def __init__(self, data_root: Path) -> None:
        self.path = Path(data_root).resolve() / "settings.json"

    def _raw(self) -> dict:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def get(self) -> SystemSettings:
        raw = self._raw()
        ui = raw.get("ui")
        if isinstance(ui, dict) and "primary_destination" not in ui and ui.get("skill_catalog_open") is True:
            ui["primary_destination"] = "skills"
        raw["version"] = 3
        raw["app_version"] = APP_VERSION
        return SystemSettings.model_validate(raw)

    def update(self, update: SettingsUpdate) -> SystemSettings:
        raw = self._raw()
        current = self.get()
        if update.ui is not None:
            merged_ui = {
                **current.ui.model_dump(),
                **update.ui.model_dump(exclude_unset=True, exclude_none=True),
            }
            current.ui = UiSettings.model_validate(merged_ui)
        if update.skill_scan is not None:
            resolved = []
            for value in update.skill_scan.approved_directories:
                path = str(Path(value).resolve())
                if path not in resolved:
                    resolved.append(path)
            current.skill_scan.approved_directories = resolved
        if update.skill_routing is not None:
            current.skill_routing = SkillRoutingSettings.model_validate(update.skill_routing)
        if update.gpu_optimization is not None:
            known_models = set(load_config().get("jury_models", []))
            unknown = set(update.gpu_optimization.model_profiles) - known_models
            if unknown:
                raise ValueError(f"Unknown model profile: {sorted(unknown)[0]}")
            current.gpu_optimization = GpuOptimizationSettings.model_validate(update.gpu_optimization)
        if update.designer is not None:
            current.designer = DesignerSettings.model_validate(update.designer)
        if update.autonomous_coding is not None:
            current.autonomous_coding = AutonomousCodingSettings.model_validate(update.autonomous_coding)
        raw["version"] = current.version
        raw["app_version"] = APP_VERSION
        saved_ui = raw.setdefault("ui", {})
        for field, value in current.ui.model_dump().items():
            saved_ui[field] = value
        raw.setdefault("skill_scan", {})["approved_directories"] = current.skill_scan.approved_directories
        raw["skill_routing"] = current.skill_routing.model_dump()
        raw["gpu_optimization"] = current.gpu_optimization.model_dump()
        raw["designer"] = current.designer.model_dump()
        raw["autonomous_coding"] = current.autonomous_coding.model_dump()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / f".settings-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        return current

    def optimization_for(self, model: str) -> GpuProfileSettings:
        settings = self.get().gpu_optimization
        return settings.model_profiles.get(model, settings.default_profile)
