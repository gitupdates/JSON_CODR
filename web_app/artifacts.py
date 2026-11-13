import re
import zipfile
from pathlib import Path, PurePosixPath

from web_app.models import ArtifactRecord, GeneratedFile
from web_app.workspace import WorkspaceService


class ArtifactService:
    def __init__(self, workspace: WorkspaceService) -> None:
        self.workspace = workspace

    def save_conversion(self, session_id: str, source_name: str, files: list[GeneratedFile]) -> ArtifactRecord:
        self.workspace.get_session(session_id)
        if not files:
            raise ValueError("Conversion produced no files")
        if len(files) > 50:
            raise ValueError("Conversion produced too many files")
        if sum(len(item.content.encode("utf-8")) for item in files) > 2 * 1024 * 1024:
            raise ValueError("Conversion output exceeds size limit")
        normalized: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in files:
            path = PurePosixPath(item.path.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or not path.name:
                raise ValueError("Generated file has an unsafe path")
            name = path.as_posix()
            if name.casefold() in seen:
                raise ValueError("Generated file paths must be unique")
            seen.add(name.casefold())
            normalized.append((name, item.content))
        stem = Path(source_name).stem
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "conversion"
        filename = f"{safe_stem}-converted.zip"
        artifacts = self.workspace.sessions_root / session_id / "artifacts"
        artifacts.mkdir(exist_ok=True)
        destination = artifacts / filename
        temporary = artifacts / f".{filename}.tmp"
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in normalized:
                archive.writestr(name, content.encode("utf-8"))
        temporary.replace(destination)
        return ArtifactRecord(filename=filename, path=str(destination.resolve()))

    def artifact_path(self, session_id: str, filename: str) -> Path:
        self.workspace.get_session(session_id)
        if Path(filename).name != filename or not filename.endswith("-converted.zip"):
            raise ValueError("Invalid artifact filename")
        path = self.workspace.sessions_root / session_id / "artifacts" / filename
        if not path.is_file():
            raise KeyError(filename)
        return path
