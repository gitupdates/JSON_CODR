import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from web_app.attachments import AttachmentService


@dataclass
class DependencySuggestion:
    ecosystem: str
    source: str
    command: str
    automatic: bool = False


_NPM_NAME = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+$", re.IGNORECASE)
_NPM_VERSION = re.compile(r"^[A-Za-z0-9.*+^~<>=| -]+$")


def _valid_python_spec(spec: str) -> bool:
    try:
        return Requirement(spec).url is None
    except InvalidRequirement:
        return False


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class DependencyPreflight:
    def missing_python(self, specs: list[str]) -> list[str]:
        missing: list[str] = []
        for spec in specs:
            try:
                requirement = Requirement(spec)
            except InvalidRequirement:
                missing.append(spec)
                continue
            if requirement.marker and not requirement.marker.evaluate():
                continue
            try:
                installed_version = metadata.version(requirement.name)
                if requirement.specifier and not requirement.specifier.contains(installed_version, prereleases=True):
                    missing.append(spec)
            except Exception:
                missing.append(spec)
        return missing

    def missing_node(self, packages: list[str], cwd: Path) -> list[str]:
        npm = shutil.which("npm")
        if npm is None:
            return list(packages)
        def check(package: str) -> str | None:
            try:
                result = subprocess.run(
                    [npm, "ls", package, "--depth=0", "--json"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return package
            return package if result.returncode != 0 else None

        workers = min(8, len(packages))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            return [package for package in executor.map(check, packages) if package is not None]


class DependencyService:
    def __init__(
        self,
        attachments: AttachmentService,
        preflight: DependencyPreflight | None = None,
        install_root: Path | None = None,
    ) -> None:
        self.attachments = attachments
        self.preflight = preflight or DependencyPreflight()
        self.install_root = install_root or Path(__file__).resolve().parent.parent

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
                specs = [spec for spec in specs if _valid_python_spec(spec)]
                if specs:
                    missing = self.preflight.missing_python(specs[:100])
                    if missing:
                        quoted = " ".join(_powershell_literal(spec) for spec in missing)
                        suggestions.append(DependencySuggestion("python", record.display_name, f"python -m pip install {quoted}", True))
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
                    missing = self.preflight.missing_node(packages[:100], self.install_root)
                    if missing:
                        quoted = " ".join(_powershell_literal(package) for package in missing)
                        suggestions.append(DependencySuggestion("node", record.display_name, f"npm install {quoted}", True))
        return suggestions
