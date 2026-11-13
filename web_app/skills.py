import json
import hashlib
import os
import re
import shutil
import threading
import uuid
import zipfile
import tempfile
import time
from pathlib import Path, PurePosixPath

from web_app.models import SkillDiscovery, SkillPack, SkillRecord, SkillScanResult


class DuplicateSkillPack(ValueError):
    pass


SKILL_ENVELOPE_MARKER = "JSON_CODR_SKILL_SCHEMA: 1"


def _wrap_skill_content(name: str, description: str, content: str) -> str:
    if SKILL_ENVELOPE_MARKER in content:
        return content
    capability_match = re.search(r"(?mi)^(?:capabilities|required-capabilities):\s*([^\n]+)", content)
    capabilities = capability_match.group(1).strip() if capability_match else "Use only capabilities available and authorized in JSON_CODR"
    intent = description or f"Apply the {name} workflow to the current user request"
    return (
        "--- JSON_CODR SKILL ENVELOPE ---\n"
        f"{SKILL_ENVELOPE_MARKER}\n"
        f"NAME: {name}\n"
        f"INTENT: {intent}\n"
        f"CAPABILITIES: {capabilities}\n"
        "SYNTAX: Select this skill for the active session. Treat {{arguments}} as the current user request when present.\n"
        "EXECUTION_DIRECTIVE: Apply this active saved skill automatically with any selected LLM. Follow the converted instructions in order, use only available authorized capabilities, and report unavailable requirements honestly.\n"
        "--- BEGIN CONVERTED SKILL ---\n"
        f"{content.strip()}\n"
        "--- END CONVERTED SKILL ---\n"
    )


def _skill_fingerprint(skill: SkillRecord) -> str:
    content = (skill.original_content or skill.content).replace("\r\n", "\n").strip()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "skill"


class SkillConverterService:
    def __init__(self, max_entries: int = 200, max_bytes: int = 10 * 1024 * 1024) -> None:
        self.max_entries = max_entries
        self.max_bytes = max_bytes

    def convert(self, source: Path, source_name: str) -> SkillPack:
        entries: dict[str, str] = {}
        names: list[str] = []
        if Path(source_name).suffix.casefold() == ".7z":
            import py7zr
            from py7zr.io import BytesIOFactory

            try:
                with py7zr.SevenZipFile(source) as archive:
                    if archive.needs_password():
                        raise ValueError("Encrypted skill archives are not supported")
                    infos = [item for item in archive.list() if item.is_file]
                    if len(infos) > self.max_entries:
                        raise ValueError("Skill archive contains too many entries")
                    if sum(item.uncompressed or 0 for item in infos) > self.max_bytes:
                        raise ValueError("Skill archive uncompressed size exceeds limit")
                    names = [item.filename.replace("\\", "/") for item in infos]
                    selected = []
                    for name in names:
                        path = PurePosixPath(name)
                        if path.is_absolute() or ".." in path.parts:
                            raise ValueError("Skill archive contains an unsafe path")
                        if path.suffix.casefold() == ".md":
                            selected.append(name)
                    factory = BytesIOFactory(self.max_bytes)
                    if selected:
                        archive.extract(targets=selected, factory=factory)
                    for name in selected:
                        try:
                            entries[PurePosixPath(name).as_posix()] = factory.get(name).read().decode("utf-8")
                        except UnicodeDecodeError:
                            continue
            except ValueError:
                raise
            except Exception as error:
                raise ValueError("Malformed skill archive") from error
        else:
            try:
                with zipfile.ZipFile(source) as archive:
                    infos = [item for item in archive.infolist() if not item.is_dir()]
                    if len(infos) > self.max_entries:
                        raise ValueError("Skill archive contains too many entries")
                    if sum(item.file_size for item in infos) > self.max_bytes:
                        raise ValueError("Skill archive uncompressed size exceeds limit")
                    for item in infos:
                        path = PurePosixPath(item.filename.replace("\\", "/"))
                        if path.is_absolute() or ".." in path.parts:
                            raise ValueError("Skill archive contains an unsafe path")
                        if path.suffix.casefold() != ".md":
                            continue
                        try:
                            entries[path.as_posix()] = archive.read(item).decode("utf-8")
                        except UnicodeDecodeError:
                            continue
                    names = [item.filename.replace("\\", "/") for item in infos]
            except zipfile.BadZipFile as error:
                raise ValueError("Malformed skill archive") from error
        if any("/.claude-plugin/" in f"/{name}" for name in names):
            source_format = "claude"
        elif any(name.endswith("/SKILL.md") or name == "SKILL.md" for name in names):
            source_format = "codex"
        else:
            source_format = "generic"
        skills: list[SkillRecord] = []
        used: set[str] = set()
        candidates = {
            name: content for name, content in entries.items()
            if name == "SKILL.md"
            or name.endswith("/SKILL.md")
            or source_format == "generic"
            or (source_format == "claude" and any(part in PurePosixPath(name).parts for part in ("commands", "agents")))
        }
        for path, content in candidates.items():
            fallback = PurePosixPath(path).parent.name if path.endswith("/SKILL.md") else PurePosixPath(path).stem
            name_match = re.search(r"(?m)^name:\s*([^\n]+)", content)
            description_match = re.search(r"(?m)^description:\s*([^\n]+)", content)
            name = (name_match.group(1).strip() if name_match else fallback) or "skill"
            skill_id = _slug(name)
            suffix = 2
            while skill_id in used:
                skill_id = f"{_slug(name)}-{suffix}"
                suffix += 1
            used.add(skill_id)
            converted = self._normalize_content(content)
            compatibility = (
                "\n\n## JSON_CODR compatibility\n"
                "Treat named provider tools as capability requirements. Use only capabilities available in the current session, "
                "ask before running CLI commands, and never claim an unavailable action completed.\n"
            )
            description = description_match.group(1).strip() if description_match else ""
            skills.append(SkillRecord(
                id=skill_id,
                name=name,
                description=description,
                content=_wrap_skill_content(name, description, converted + compatibility),
                original_content=content,
            ))
        if not skills:
            raise ValueError("Archive contains no supported Markdown skills")
        pack_name = Path(source_name).stem
        return SkillPack(
            id=_slug(pack_name),
            name=pack_name,
            source_format=source_format,
            source_name=source_name,
            source_path=str(Path(source).resolve()),
            source_digest=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
            skills=skills,
        )

    @staticmethod
    def _normalize_content(content: str) -> str:
        converted = re.sub(r"(?m)^tools:\s*(.+)$", r"capabilities: \1", content)
        converted = re.sub(
            r"(?m)^allowed-tools:\s*\n((?:\s+-\s+.+\n?)*)",
            lambda match: "required-capabilities:\n" + match.group(1),
            converted,
        )
        replacements = {
            "Claude Code": "JSON_CODR",
            "$ARGUMENTS": "{{arguments}}",
            "AskUserQuestion": "ask_user",
            "TodoWrite": "task_checklist",
            "Task(": "run_role_sequentially(",
            "Agent(": "run_role_sequentially(",
        }
        for original, replacement in replacements.items():
            converted = converted.replace(original, replacement)
        return converted


class SkillLibraryService:
    def __init__(self, data_root: Path) -> None:
        self.root = Path(data_root).resolve() / "skill_library"
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.root / "catalog.json"
        self.sources_root = self.root / "sources"
        self.sources_root.mkdir(exist_ok=True)
        self._lock = threading.Lock()

    def list(self) -> list[SkillPack]:
        if not self.catalog_path.is_file():
            return []
        return [SkillPack.model_validate(item) for item in json.loads(self.catalog_path.read_text(encoding="utf-8"))]

    def _save(self, packs: list[SkillPack]) -> None:
        temporary = self.root / f".catalog-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps([pack.model_dump(mode="json") for pack in packs], indent=2), encoding="utf-8")
        os.replace(temporary, self.catalog_path)

    def ensure_envelopes(self) -> None:
        with self._lock:
            packs = self.list()
            changed = False
            for pack in packs:
                for index, skill in enumerate(pack.skills):
                    wrapped = _wrap_skill_content(skill.name, skill.description, skill.content)
                    if wrapped != skill.content:
                        pack.skills[index] = skill.model_copy(update={"content": wrapped})
                        changed = True
            if changed:
                self._save(packs)

    def install(self, pack: SkillPack) -> SkillPack:
        with self._lock:
            packs = self.list()
            installed_digests = {item.source_digest for item in packs if item.source_digest}
            installed_skills = {_skill_fingerprint(skill) for item in packs for skill in item.skills}
            incoming_skills = {_skill_fingerprint(skill) for skill in pack.skills}
            if (pack.source_digest and pack.source_digest in installed_digests) or incoming_skills.issubset(installed_skills):
                raise DuplicateSkillPack("This skill pack is already installed")
            unique_skills = [skill for skill in pack.skills if _skill_fingerprint(skill) not in installed_skills]
            pack = pack.model_copy(update={"skills": unique_skills})
            existing = {item.id for item in packs}
            base = pack.id
            suffix = 2
            while pack.id in existing:
                pack = pack.model_copy(update={"id": f"{base}-{suffix}"})
                suffix += 1
            source = Path(pack.source_path) if pack.source_path else None
            if source and source.is_file():
                preserved = self.sources_root / f"{pack.id}{source.suffix.casefold()}"
                shutil.copy2(source, preserved)
                pack = pack.model_copy(update={"source_path": str(preserved.resolve())})
            packs.append(pack)
            self._save(packs)
            return pack

    def deduplicate(self) -> dict[str, object]:
        with self._lock:
            retained: list[SkillPack] = []
            seen_digests: set[str] = set()
            seen_skills: set[str] = set()
            removed_pack_ids: list[str] = []
            removed_skills = 0
            for pack in self.list():
                fingerprints = [_skill_fingerprint(skill) for skill in pack.skills]
                duplicate_source = bool(pack.source_digest and pack.source_digest in seen_digests)
                unique_skills = [
                    skill for skill, fingerprint in zip(pack.skills, fingerprints)
                    if fingerprint not in seen_skills
                ]
                removed_skills += len(pack.skills) - len(unique_skills)
                if duplicate_source or not unique_skills:
                    if duplicate_source:
                        removed_skills += len(unique_skills)
                    removed_pack_ids.append(pack.id)
                    continue
                updated = pack.model_copy(update={"skills": unique_skills})
                retained.append(updated)
                if pack.source_digest:
                    seen_digests.add(pack.source_digest)
                seen_skills.update(_skill_fingerprint(skill) for skill in unique_skills)
            self._save(retained)
            return {
                "removed_packs": len(removed_pack_ids),
                "removed_skills": removed_skills,
                "removed_pack_ids": removed_pack_ids,
            }

    def get_skill(self, pack_id: str, skill_id: str) -> SkillRecord:
        for pack in self.list():
            if pack.id == pack_id:
                for skill in pack.skills:
                    if skill.id == skill_id:
                        return skill
        raise KeyError(f"{pack_id}:{skill_id}")

    def documentation(self, pack_id: str, skill_id: str) -> str:
        skill = self.get_skill(pack_id, skill_id)
        capabilities = re.search(r"(?mi)^(?:capabilities|required-capabilities):\s*([^\n]+)", skill.content)
        abilities = capabilities.group(1).strip() if capabilities else "Follow the documented instructions using capabilities available in JSON_CODR."
        syntax = "Select this skill for the active session, then provide the task in the prompt."
        if "{{arguments}}" in skill.content:
            syntax += " The `{{arguments}}` placeholder represents the user's task input."
        intent = skill.description or f"Apply the {skill.name} workflow to the active request."
        return (
            f"# {skill.name}\n\n## Intent\n\n{intent}\n\n"
            f"## Abilities\n\n{abilities}\n\n"
            f"## Command structure and syntax\n\n{syntax}\n\n"
            f"## Example use cases\n\n- Select **{skill.name}**, enter a relevant task, and run the chosen local model.\n"
            f"- Edit the instructions, save the skill, and apply it to the current session.\n\n"
            "## Compatibility\n\nThis converted JSON_CODR skill is provider-neutral. Tool names are capability requirements and run only when the current system provides and authorizes them.\n\n"
            f"## Instructions\n\n{skill.content}\n"
        )

    def update_skill(self, pack_id: str, skill_id: str, content: str, enabled: bool) -> SkillRecord:
        with self._lock:
            packs = self.list()
            for pack in packs:
                if pack.id != pack_id:
                    continue
                for index, skill in enumerate(pack.skills):
                    if skill.id == skill_id:
                        updated = skill.model_copy(update={"content": _wrap_skill_content(skill.name, skill.description, content), "enabled": enabled})
                        pack.skills[index] = updated
                        self._save(packs)
                        return updated
        raise KeyError(f"{pack_id}:{skill_id}")

    def rename(self, pack_id: str, name: str) -> SkillPack:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Skill pack name cannot be empty")
        with self._lock:
            packs = self.list()
            for index, pack in enumerate(packs):
                if pack.id == pack_id:
                    renamed = pack.model_copy(update={"name": normalized})
                    packs[index] = renamed
                    self._save(packs)
                    return renamed
        raise KeyError(pack_id)

    def remove(self, pack_id: str) -> None:
        with self._lock:
            packs = self.list()
            retained = [pack for pack in packs if pack.id != pack_id]
            if len(retained) == len(packs):
                raise KeyError(pack_id)
            self._save(retained)


class SkillDiscoveryService:
    def __init__(self, library: SkillLibraryService, converter: SkillConverterService, data_root: Path, known_roots: list[Path] | None = None) -> None:
        self.library = library
        self.converter = converter
        self.data_root = Path(data_root).resolve()
        home = Path.home()
        self.known_roots = known_roots or [home / ".codex" / "skills", home / ".claude" / "skills"]
        self._previews: dict[str, dict] = {}
        self._tokens: dict[str, float] = {}

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        if path.is_file():
            digest.update(path.read_bytes())
        else:
            for item in sorted(path.rglob("*")):
                if item.is_file() and not item.is_symlink():
                    digest.update(item.relative_to(path).as_posix().encode())
                    digest.update(item.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _folder_archive(path: Path) -> Path:
        handle, filename = tempfile.mkstemp(suffix=".zip")
        os.close(handle)
        target = Path(filename)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            for item in path.rglob("*"):
                if item.is_file() and not item.is_symlink():
                    bundle.write(item, item.relative_to(path).as_posix())
        return target

    def _convert_source(self, path: Path) -> SkillPack:
        if path.is_dir():
            archive = self._folder_archive(path)
            try:
                return self.converter.convert(archive, f"{path.name}.zip")
            finally:
                archive.unlink(missing_ok=True)
        return self.converter.convert(path, path.name)

    def _already_installed(self, pack: SkillPack) -> bool:
        installed = {_skill_fingerprint(skill) for item in self.library.list() for skill in item.skills}
        return all(_skill_fingerprint(skill) in installed for skill in pack.skills)

    def scan(self, directory: Path | str) -> SkillScanResult:
        root = Path(directory).resolve()
        if not root.is_dir() or root.is_symlink():
            raise ValueError("Skill scan path must be an existing local directory")
        candidates: list[Path] = []
        warnings: list[str] = []
        entries = 0
        for item in root.rglob("*"):
            depth = len(item.relative_to(root).parts)
            if depth > 5 or item.is_symlink():
                continue
            entries += 1
            if entries > 500:
                warnings.append("Scan stopped after 500 entries")
                break
            if item.is_file() and item.suffix.casefold() in {".zip", ".7z"}:
                candidates.append(item)
            elif item.is_file() and item.name == "SKILL.md":
                candidates.append(item.parent)
        if (root / "SKILL.md").is_file():
            candidates.insert(0, root)
        discoveries: list[SkillDiscovery] = []
        seen: set[Path] = set()
        for source in candidates:
            if source in seen:
                continue
            seen.add(source)
            try:
                pack = self._convert_source(source)
            except ValueError as error:
                warnings.append(f"{source.name}: {error}")
                continue
            discovery_id = uuid.uuid4().hex
            self._previews[discovery_id] = {
                "path": source,
                "digest": self._digest(source),
                "expires": time.monotonic() + 600,
            }
            discoveries.append(SkillDiscovery(
                id=discovery_id,
                name=pack.name,
                source_format=pack.source_format,
                source_path=str(source),
                skill_count=len(pack.skills),
                already_installed=self._already_installed(pack),
            ))
        token = None
        if not discoveries:
            token = uuid.uuid4().hex
            self._tokens[token] = time.monotonic() + 600
        return SkillScanResult(discoveries=discoveries, warnings=warnings, fallback_token=token)

    def scan_known(self, fallback_token: str) -> SkillScanResult:
        expiry = self._tokens.pop(fallback_token, None)
        if expiry is None or expiry < time.monotonic():
            raise ValueError("Known-location scan requires a recent empty explicit scan")
        combined = SkillScanResult()
        for root in self.known_roots:
            if not root.is_dir():
                continue
            result = self.scan(root)
            combined.discoveries.extend(result.discoveries)
            combined.warnings.extend(result.warnings)
        return combined

    def install(self, discovery_id: str) -> SkillPack:
        preview = self._previews.pop(discovery_id, None)
        if preview is None or preview["expires"] < time.monotonic():
            raise ValueError("Discovery preview expired; scan again")
        source = preview["path"]
        if not source.exists() or self._digest(source) != preview["digest"]:
            raise ValueError("Skill source changed after preview; scan again")
        if source.is_dir():
            archive = self._folder_archive(source)
            try:
                pack = self.converter.convert(archive, f"{source.name}.zip")
                return self.library.install(pack)
            finally:
                archive.unlink(missing_ok=True)
        return self.library.install(self.converter.convert(source, source.name))
