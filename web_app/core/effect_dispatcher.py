from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta

from web_app.core.contracts import EffectIntent, EffectState
from web_app.core.store import TaskStore


EffectHandler = Callable[[EffectIntent], Awaitable[None]]


class EffectDispatcher:
    def __init__(
        self,
        store: TaskStore,
        handlers: Mapping[str, EffectHandler],
        *,
        owner: str,
        concurrency: int = 2,
        lease_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        if concurrency < 1:
            raise ValueError("effect dispatcher concurrency must be positive")
        self._store = store
        self._handlers = dict(handlers)
        self._owner = owner
        self._concurrency = concurrency
        self._lease_duration = lease_duration

    async def drain_once(self) -> int:
        leased = self._store.lease_pending_effects(
            owner=self._owner,
            limit=self._concurrency,
            lease_duration=self._lease_duration,
        )
        if not leased:
            return 0
        await asyncio.gather(*(self._dispatch(intent) for intent in leased))
        return len(leased)

    async def _dispatch(self, intent: EffectIntent) -> None:
        handler = self._handlers.get(intent.capability_id)
        if handler is None:
            self._store.transition_effect(
                intent.task_id,
                intent.effect_id,
                EffectState.failed,
                expected_state=EffectState.leased,
            )
            return
        running = self._store.transition_effect(
            intent.task_id,
            intent.effect_id,
            EffectState.running,
            expected_state=EffectState.leased,
        )
        try:
            await handler(running)
        except Exception:
            self._store.transition_effect(
                intent.task_id,
                intent.effect_id,
                EffectState.unknown_requires_reconciliation,
                expected_state=EffectState.running,
            )
            return
        self._store.transition_effect(
            intent.task_id,
            intent.effect_id,
            EffectState.succeeded,
            expected_state=EffectState.running,
        )
