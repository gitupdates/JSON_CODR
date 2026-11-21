"""Stable, serializable records for the security persistence boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class SecurityRecord(BaseModel):
    """Base model that rejects accidental, unversioned security data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    created_at: datetime
    updated_at: datetime
    version: int

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("security timestamps must be UTC-aware")
        return value

    @field_validator("version")
    @classmethod
    def version_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("version must be positive")
        return value


class AccountRecord(SecurityRecord):
    """A local account whose UUID remains stable when its username changes."""

    account_id: UUID
    username: str
    username_casefold: str | None = None
    status: str

    @field_validator("username")
    @classmethod
    def username_must_be_present(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("username must not be empty")
        return normalized

    @model_validator(mode="after")
    def username_casefold_must_match_username(self) -> "AccountRecord":
        expected = self.username.casefold()
        if self.username_casefold is None:
            object.__setattr__(self, "username_casefold", expected)
        elif self.username_casefold != expected:
            raise ValueError("username_casefold must match username.casefold()")
        return self


class GroupRecord(SecurityRecord):
    """A stable group record; immutable stable IDs survive display-name edits."""

    group_id: UUID
    stable_id: str
    display_name: str
    description: str = ""

    @field_validator("stable_id", "display_name")
    @classmethod
    def required_text_must_be_present(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("group identifiers and names must not be empty")
        return normalized


class SessionRecord(SecurityRecord):
    """Server-side session metadata; only a token hash is persisted."""

    session_id: UUID
    account_id: UUID
    token_hash: str
    issued_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    last_seen_at: datetime
    policy_epoch: int
    recent_auth_at: datetime | None = None
    revoked_at: datetime | None = None

    @field_validator(
        "issued_at",
        "idle_expires_at",
        "absolute_expires_at",
        "last_seen_at",
        "recent_auth_at",
        "revoked_at",
    )
    @classmethod
    def session_timestamp_must_be_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value)):
            raise ValueError("session timestamps must be UTC-aware")
        return value

    @field_validator("token_hash")
    @classmethod
    def token_hash_must_be_present(cls, value: str) -> str:
        if not value:
            raise ValueError("token_hash must not be empty")
        return value

    @field_validator("policy_epoch")
    @classmethod
    def policy_epoch_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("policy_epoch must not be negative")
        return value
