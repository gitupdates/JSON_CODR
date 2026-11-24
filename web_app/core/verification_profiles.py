from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from pydantic import Field, field_validator

from web_app.core.contracts import FrozenContract


_PROFILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")
_INTERPRETERS = frozenset({
    "cmd", "cmd.exe", "command.com", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "bash", "bash.exe", "sh", "sh.exe", "zsh", "zsh.exe",
})
PROFILE_ADMINISTRATION_SCOPE = "verification.profiles.manage"


def _is_absolute(value: str) -> bool:
    return Path(value).is_absolute() or PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


class VerificationProfile(FrozenContract):
    """Administrator-authored, deterministic command definition for autonomous verification."""

    profile_id: str = Field(min_length=1, max_length=128)
    executable: str = Field(min_length=1, max_length=4096)
    argument_template: tuple[str, ...] = Field(default_factory=tuple)
    cwd_rule: str = Field(min_length=1, max_length=4096)
    timeout_seconds: int = Field(ge=1, le=300)
    max_output_bytes: int = Field(ge=1024, le=8_388_608)
    network_policy: str

    @field_validator("profile_id")
    @classmethod
    def valid_profile_id(cls, value: str) -> str:
        if not _PROFILE_ID.fullmatch(value):
            raise ValueError("profile id is invalid")
        return value

    @field_validator("executable")
    @classmethod
    def safe_executable(cls, value: str) -> str:
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("executable contains control characters")
        if Path(value).name.casefold() in _INTERPRETERS:
            raise ValueError("shell interpreter executables are not allowed")
        if not _is_absolute(value):
            raise ValueError("executable must use an exact absolute path")
        return value

    @field_validator("argument_template")
    @classmethod
    def safe_arguments(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if "\x00" in value or "\n" in value or "\r" in value:
                raise ValueError("argument template contains control characters")
            if _is_absolute(value):
                raise ValueError("absolute path arguments are not allowed")
        return values

    @field_validator("cwd_rule")
    @classmethod
    def safe_cwd_rule(cls, value: str) -> str:
        if value == "project_root":
            return value
        if _is_absolute(value) or "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("cwd rule must be relative to the project root")
        return value

    @field_validator("network_policy")
    @classmethod
    def valid_network_policy(cls, value: str) -> str:
        if value not in {"allow", "deny"}:
            raise ValueError("network policy must be allow or deny")
        return value


class VerificationProfileStore:
    """Tamper-evident profile store below the application data root."""

    def __init__(self, data_root: str | Path) -> None:
        self._root = Path(data_root).resolve()
        self.path = self._root / "core" / "verification_profiles.json"

    def replace(self, profiles: tuple[VerificationProfile, ...], *, scopes: tuple[str, ...] = ()) -> str:
        if PROFILE_ADMINISTRATION_SCOPE not in scopes:
            raise PermissionError("verification profile administration scope is required")
        if len({profile.profile_id for profile in profiles}) != len(profiles):
            raise ValueError("verification profile ids must be unique")
        canonical_profiles = [profile.model_dump(mode="json") for profile in sorted(profiles, key=lambda item: item.profile_id)]
        document = {"profiles": canonical_profiles}
        document["digest"] = self._digest(document)
        payload = self._canonical(document).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return str(document["digest"])

    def resolve(self, profile_id: str) -> VerificationProfile:
        return self._profiles()[profile_id]

    def profile_digest(self) -> str:
        document = self._document()
        return str(document["digest"])

    def _profiles(self) -> dict[str, VerificationProfile]:
        document = self._document()
        profiles = tuple(VerificationProfile.model_validate(item) for item in document["profiles"])
        if len({profile.profile_id for profile in profiles}) != len(profiles):
            raise ValueError("verification profile ids must be unique")
        return {profile.profile_id: profile for profile in profiles}

    def _document(self) -> dict[str, object]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise KeyError("verification profile store is not configured") from error
        if not isinstance(document, dict) or not isinstance(document.get("profiles"), list) or not isinstance(document.get("digest"), str):
            raise ValueError("verification profile store is invalid")
        expected = self._digest({"profiles": document["profiles"]})
        if document["digest"] != expected:
            raise ValueError("verification profile digest does not match")
        return document

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _digest(cls, document: dict[str, object]) -> str:
        return f"sha256:{hashlib.sha256(cls._canonical(document).encode('utf-8')).hexdigest()}"


def render_profile_arguments(profile: VerificationProfile, values: dict[str, object]) -> tuple[str, ...]:
    """Expand only named profile placeholders using scalar, non-path values."""
    placeholders = set()
    for template in profile.argument_template:
        placeholders.update(_PLACEHOLDER.findall(template))
    if set(values) != placeholders:
        raise ValueError("profile template values do not match the profile")
    rendered: list[str] = []
    for template in profile.argument_template:
        def substitute(match: re.Match[str]) -> str:
            value = values[match.group(1)]
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError("profile template value must be scalar")
            return str(value)

        value = _PLACEHOLDER.sub(substitute, template)
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("profile argument contains control characters")
        if _is_absolute(value):
            raise ValueError("absolute path arguments are not allowed")
        rendered.append(value)
    return tuple(rendered)
