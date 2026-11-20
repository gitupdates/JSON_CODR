from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field, field_validator

from web_app.core.contracts import FrozenContract


class ProviderManifest(FrozenContract):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = Field(min_length=1)
    python_versions: tuple[str, ...] = Field(min_length=1)
    packages: Mapping[str, str]
    probe_operation: str = Field(min_length=1)
    network_policy: str = "disabled"
    mounts: tuple[str, ...] = ()

    @field_validator("packages")
    @classmethod
    def validate_hashes(cls, packages: Mapping[str, str]) -> Mapping[str, str]:
        if not packages or any(
            not digest.startswith("sha256:") or len(digest) != 71
            for digest in packages.values()
        ):
            raise ValueError("provider packages require sha256 locks")
        return packages


class ProviderLock(FrozenContract):
    provider_id: str
    version: str
    python: str
    packages: Mapping[str, str]
    network_policy: str
    mounts: tuple[str, ...]


class ProviderProcess(FrozenContract):
    provider_id: str
    version: str
    root: str
    python: str
    ready: bool


class ProviderRequest(FrozenContract):
    protocol_version: str = "1"
    call_id: str
    operation: str
    payload: Mapping


class ProviderEvent(FrozenContract):
    protocol_version: str = "1"
    call_id: str
    event_type: str
    payload: Mapping
