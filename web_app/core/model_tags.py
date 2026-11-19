from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Collection, Mapping
from urllib.parse import urlparse

from web_app.core.project_intelligence import ProjectReader


@dataclass(frozen=True)
class ModelTag:
    models: tuple[str, ...]
    skills: tuple[str, ...]
    endpoint: str = "http://127.0.0.1:11434"
    num_ctx: int | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class ModelTagRoute:
    requested: str
    effective_model: str
    fallback_used: bool
    unavailable_models: tuple[str, ...]
    endpoint: str | None = None
    options: Mapping[str, int | float] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class CompiledPrompt:
    text: str
    instruction_paths: tuple[str, ...]
    skill_paths: tuple[str, ...]


class ModelTagRegistry:
    def __init__(self, tags: Mapping[str, ModelTag], fallback_order: tuple[str, ...]) -> None:
        self.tags = MappingProxyType(dict(tags))
        self.fallback_order = fallback_order

    @classmethod
    def load(cls, path: Path) -> "ModelTagRegistry":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise ValueError
            fallback_order = cls._strings(payload.get("fallback_order"))
            raw_tags = payload.get("tags")
            if not isinstance(raw_tags, dict):
                raise ValueError
            tags = {}
            for name, raw in raw_tags.items():
                if not isinstance(name, str) or not name or not isinstance(raw, dict):
                    raise ValueError
                endpoint = str(raw.get("endpoint", "http://127.0.0.1:11434"))
                parsed_endpoint = urlparse(endpoint)
                if parsed_endpoint.scheme != "http" or parsed_endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
                    raise ValueError
                num_ctx = raw.get("num_ctx")
                temperature = raw.get("temperature")
                if num_ctx is not None and (not isinstance(num_ctx, int) or not 512 <= num_ctx <= 1_048_576):
                    raise ValueError
                if temperature is not None and (not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2):
                    raise ValueError
                tags[name] = ModelTag(
                    models=cls._strings(raw.get("models")),
                    skills=cls._strings(raw.get("skills", [])),
                    endpoint=endpoint,
                    num_ctx=num_ctx,
                    temperature=float(temperature) if temperature is not None else None,
                )
                if not tags[name].models:
                    raise ValueError
            return cls(tags, fallback_order)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError("invalid model registry") from error

    def resolve(self, tag: str, installed_models: Collection[str]) -> ModelTagRoute:
        installed = frozenset(installed_models)
        if tag in installed:
            return ModelTagRoute(tag, tag, False, ())
        candidates = self.tags[tag].models if tag in self.tags else (tag, *self.fallback_order)
        unavailable = tuple(model for model in candidates if model not in installed)
        effective = next((model for model in candidates if model in installed), None)
        if effective is None:
            raise ValueError(f"no installed model can satisfy {tag}")
        tag_config = self.tags.get(tag)
        options = {}
        if tag_config and tag_config.num_ctx is not None:
            options["num_ctx"] = tag_config.num_ctx
        if tag_config and tag_config.temperature is not None:
            options["temperature"] = tag_config.temperature
        return ModelTagRoute(
            tag,
            effective,
            effective != tag,
            unavailable,
            endpoint=tag_config.endpoint if tag_config else None,
            options=MappingProxyType(options),
        )

    def compile_prompt(
        self,
        tag: str,
        project_root: Path,
        task: str,
        *,
        target: str | Path = ".",
    ) -> CompiledPrompt:
        reader = ProjectReader(project_root)
        instructions = reader.instructions_for(target)
        tag_config = self.tags.get(tag)
        skill_paths = tag_config.skills if tag_config else ()
        sections = [
            *(f"PROJECT INSTRUCTION [{item.relative_path}]\n{item.content}" for item in instructions),
            *(f"SKILL [{path}]\n{self._read_skill(project_root, path)}" for path in skill_paths),
            f"TASK\n{task}",
        ]
        return CompiledPrompt(
            text="\n\n".join(sections),
            instruction_paths=tuple(item.relative_path for item in instructions),
            skill_paths=skill_paths,
        )

    @staticmethod
    def _read_skill(project_root: Path, relative_path: str) -> str:
        root = project_root.resolve()
        path = (root / relative_path).resolve()
        if path == root or not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise ValueError("skill path escapes project root or is unavailable")
        data = path.read_bytes()
        if len(data) > 1_048_576 or b"\x00" in data:
            raise ValueError("skill file is unsupported")
        return data.decode("utf-8")

    @staticmethod
    def _strings(value) -> tuple[str, ...]:
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError
        return tuple(value)
