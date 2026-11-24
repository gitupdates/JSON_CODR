from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from pydantic import Field, field_validator

from web_app.core.contracts import FrozenContract
from web_app.core.auth import load_or_create_protected_key


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

    def __init__(
        self,
        data_root: str | Path,
        *,
        administration_resolver: Callable[..., object] | None = None,
        integrity_key: bytes | None = None,
        security_root: str | Path | None = None,
    ) -> None:
        self._root = Path(data_root).resolve()
        self.path = self._root / "core" / "verification_profiles.json"
        self._administration_resolver = administration_resolver
        protected_root = Path(security_root) if security_root is not None else self._root.parent / f".{self._root.name}-identity"
        self.integrity_key_path = protected_root / "verification_profiles.key.dpapi"
        self._integrity_key = bytes(integrity_key) if integrity_key is not None else load_or_create_protected_key(self.integrity_key_path)

    def replace(self, profiles: tuple[VerificationProfile, ...], *, credential: str | None = None) -> str:
        self._require_administrator(credential)
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

    def _require_administrator(self, credential: str | None) -> None:
        if not credential or self._administration_resolver is None:
            raise PermissionError("authenticated verification profile administration is required")
        try:
            principal = self._administration_resolver(
                credential,
                required_scope=PROFILE_ADMINISTRATION_SCOPE,
            )
        except (KeyError, PermissionError, ValueError) as error:
            raise PermissionError("authenticated verification profile administration is required") from error
        roles = set(getattr(principal, "roles", ()))
        scopes = set(getattr(principal, "scopes", ()))
        if not roles.intersection({"owner", "administrator"}):
            raise PermissionError("verification profile administration requires an Administrator")
        if PROFILE_ADMINISTRATION_SCOPE not in scopes:
            raise PermissionError("verification profile administration scope is required")
        if not getattr(principal, "credential_id", None) or not getattr(principal, "authentication_source", None):
            raise PermissionError("authenticated verification profile administration is required")

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
        if not hmac.compare_digest(document["digest"], expected):
            raise ValueError("verification profile integrity digest does not match")
        return document

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))

    def _digest(self, document: dict[str, object]) -> str:
        payload = self._canonical(document).encode("utf-8")
        return f"hmac-sha256:{hmac.new(self._integrity_key, payload, hashlib.sha256).hexdigest()}"


def render_profile_arguments(
    profile: VerificationProfile,
    values: dict[str, object],
    *,
    project_root: str | Path,
) -> tuple[str, ...]:
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
            if isinstance(value, str):
                _validate_candidate_string(value, Path(project_root).resolve(strict=True))
            return str(value)

        value = _PLACEHOLDER.sub(substitute, template)
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("profile argument contains control characters")
        if _is_absolute(value):
            raise ValueError("absolute path arguments are not allowed")
        rendered.append(value)
    return tuple(rendered)


def _validate_candidate_string(value: str, root: Path) -> None:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("profile argument contains control characters")
    if "/" in value or "\\" in value or re.search(r"(?:^|=)[A-Za-z]:", value):
        raise ValueError("profile template values cannot contain path spellings")
    if value in {".", ".."}:
        raise ValueError("profile template value cannot escape the project root")
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("profile template value escapes the project root")
