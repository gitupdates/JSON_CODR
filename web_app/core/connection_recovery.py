from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol, Sequence


class ConnectionState(StrEnum):
    ready = "ready"
    degraded = "degraded"
    unavailable = "unavailable"


class RecoveryActionClass(StrEnum):
    automatic = "automatic"
    approval_required = "approval_required"


@dataclass(frozen=True)
class ConnectionDescriptor:
    connection_id: str
    display_name: str
    kind: str
    credential_mode: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class ConnectionStatus:
    connection_id: str
    state: ConnectionState
    functional_probe: bool
    diagnostic_code: str
    detail: str | None = None


@dataclass(frozen=True)
class RecoveryAction:
    action_id: str
    label: str
    action_class: RecoveryActionClass


@dataclass(frozen=True)
class RecoveryPlan:
    connection_id: str
    revision: str
    actions: tuple[RecoveryAction, ...]


@dataclass(frozen=True)
class RecoveryActionResult:
    action_id: str
    status: str
    detail: str | None = None


@dataclass(frozen=True)
class RecoveryResult:
    connection_id: str
    action_results: tuple[RecoveryActionResult, ...]
    final_status: ConnectionStatus


@dataclass(frozen=True)
class ConnectionInventoryItem:
    descriptor: ConnectionDescriptor
    status: ConnectionStatus

    def __getattr__(self, name: str):
        if hasattr(self.descriptor, name):
            return getattr(self.descriptor, name)
        return getattr(self.status, name)


class RecoveryInProgress(RuntimeError):
    pass


class ConnectionAdapter(Protocol):
    descriptor: ConnectionDescriptor

    async def describe(self) -> ConnectionDescriptor: ...
    async def probe(self) -> ConnectionStatus: ...
    async def plan(self, status: ConnectionStatus) -> RecoveryPlan: ...
    async def recover(self, action_ids: frozenset[str]) -> tuple[RecoveryActionResult, ...]: ...
    async def verify(self) -> ConnectionStatus: ...


_TOKEN = re.compile(r"\b(?:gh[opsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_WINDOWS_USER = re.compile(r"(?i)C:\\Users\\[^\\\s]+")


def sanitize_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    return _WINDOWS_USER.sub(
        lambda _: r"C:\Users\[redacted-user]",
        _TOKEN.sub("[redacted-token]", detail),
    )


class ConnectionRecoveryService:
    def __init__(self, adapters: Sequence[ConnectionAdapter], *, max_concurrency: int = 4):
        self._adapters = {adapter.descriptor.connection_id: adapter for adapter in adapters}
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._locks = {connection_id: asyncio.Lock() for connection_id in self._adapters}
        self._confirmations: dict[tuple[str, str], tuple[str, float]] = {}

    def _adapter(self, connection_id: str) -> ConnectionAdapter:
        try:
            return self._adapters[connection_id]
        except KeyError as error:
            raise KeyError(f"unknown connection: {connection_id}") from error

    async def _inventory_item(self, adapter: ConnectionAdapter) -> ConnectionInventoryItem:
        async with self._semaphore:
            descriptor, status = await asyncio.gather(adapter.describe(), adapter.probe())
        return ConnectionInventoryItem(descriptor, self._normalize(status))

    async def inventory(self) -> tuple[ConnectionInventoryItem, ...]:
        items = await asyncio.gather(*(self._inventory_item(adapter) for adapter in self._adapters.values()))
        return tuple(sorted(items, key=lambda item: item.connection_id))

    async def status(self, connection_id: str) -> ConnectionInventoryItem:
        return await self._inventory_item(self._adapter(connection_id))

    async def preview(self, connection_id: str, action_id: str) -> dict:
        adapter = self._adapter(connection_id)
        plan = await self.plan(connection_id)
        if action_id not in {action.action_id for action in plan.actions}:
            raise ValueError(f"unknown recovery action: {action_id}")
        preview = getattr(adapter, "preview", None)
        if not callable(preview):
            raise ValueError(f"connection does not support previews: {connection_id}")
        result = await preview(action_id)
        code = secrets.token_hex(4).upper()
        self._confirmations[(connection_id, action_id)] = (
            hashlib.sha256(code.encode("ascii")).hexdigest(),
            time.monotonic() + 300,
        )
        return {**result, "confirmation_code": code, "expires_in": 300}

    async def recover_confirmed(
        self,
        connection_id: str,
        action_id: str,
        confirmation_code: str,
    ) -> RecoveryResult:
        record = self._confirmations.pop((connection_id, action_id), None)
        supplied = hashlib.sha256(confirmation_code.strip().upper().encode("ascii", errors="ignore")).hexdigest()
        if record is None or time.monotonic() >= record[1] or not hmac.compare_digest(supplied, record[0]):
            raise PermissionError("connection confirmation is invalid or expired")
        return await self.recover(
            connection_id,
            frozenset({action_id}),
            approved_action_ids=frozenset({action_id}),
        )

    async def plan(self, connection_id: str) -> RecoveryPlan:
        adapter = self._adapter(connection_id)
        return await adapter.plan(self._normalize(await adapter.probe()))

    async def recover(
        self,
        connection_id: str,
        action_ids: frozenset[str],
        *,
        approved_action_ids: frozenset[str] = frozenset(),
    ) -> RecoveryResult:
        adapter = self._adapter(connection_id)
        lock = self._locks[connection_id]
        if lock.locked():
            raise RecoveryInProgress(f"recovery already in progress: {connection_id}")

        async with lock:
            plan = await self.plan(connection_id)
            known_actions = {action.action_id for action in plan.actions}
            unknown = sorted(action_ids - known_actions)
            if unknown:
                raise ValueError(f"unknown recovery action: {', '.join(unknown)}")
            approval_required = {
                action.action_id
                for action in plan.actions
                if action.action_class == RecoveryActionClass.approval_required
            }
            unapproved = sorted((action_ids & approval_required) - approved_action_ids)
            if unapproved:
                raise PermissionError(f"recovery action requires approval: {', '.join(unapproved)}")
            action_results = await adapter.recover(action_ids)
            final_status = self._normalize(await adapter.verify())
            sanitized_results = tuple(
                replace(result, detail=sanitize_detail(result.detail))
                for result in action_results
            )
            return RecoveryResult(connection_id, sanitized_results, final_status)

    @staticmethod
    def _normalize(status: ConnectionStatus) -> ConnectionStatus:
        state = status.state
        if state == ConnectionState.ready and not status.functional_probe:
            state = ConnectionState.degraded
        return replace(status, state=state, detail=sanitize_detail(status.detail))
