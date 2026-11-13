import json
import re
from dataclasses import dataclass

from web_app.attachments import AttachmentService


@dataclass
class DependencySuggestion:
    ecosystem: str
    source: str
    command: str
    automatic: bool = False


_PYTHON_SPEC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:[!<>=~]=?[A-Za-z0-9.*+!_-]+)?$")
_NPM_NAME = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+$", re.IGNORECASE)
_NPM_VERSION = re.compile(r"^[A-Za-z0-9.*+^~<>=| -]+$")


class DependencyService:
    def __init__(self, attachments: AttachmentService) -> None:
        self.attachments = attachments

    def detect(self, session_id: str) -> list[DependencySuggestion]:
        session = self.attachments.workspace.get_session(session_id)
        suggestions: list[DependencySuggestion] = []
        for record in session.attachments:
            if record.extraction_state.value != "ready":
                continue
            name = record.display_name.casefold()
            if name in {"requirements.txt", "requirements-dev.txt"}:
                text = self.attachments.preview(session_id, record.id)["text"]
                specs = [line.strip() for line in text.splitlines()]
                specs = [spec for spec in specs if _PYTHON_SPEC.fullmatch(spec)]
                if specs:
                    quoted = " ".join(f"'{spec}'" for spec in specs[:100])
                    suggestions.append(DependencySuggestion("python", record.display_name, f"python -m pip install {quoted}"))
            elif name == "package.json":
                text = self.attachments.preview(session_id, record.id)["text"]
                try:
                    manifest = json.loads(text)
                except json.JSONDecodeError:
                    continue
                packages: list[str] = []
                for section in ("dependencies", "devDependencies"):
                    values = manifest.get(section, {})
                    if not isinstance(values, dict):
                        continue
                    for package, version in values.items():
                        if _NPM_NAME.fullmatch(str(package)) and _NPM_VERSION.fullmatch(str(version)):
                            packages.append(f"{package}@{version}")
                if packages:
                    suggestions.append(DependencySuggestion("node", record.display_name, f"npm install {' '.join(packages[:100])}"))
        return suggestions
