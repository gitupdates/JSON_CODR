from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid7

from web_app.core.adapters import CapabilityCall
from web_app.core.contracts import TaskCommand, TaskRecord
from web_app.core.service import CoreService


@dataclass
class _Schedule:
    call: CapabilityCall
    enabled: bool = True


class ScheduleService:
    def __init__(
        self, core: CoreService, *, project_id: str, project_root: str, principal: str = "user", trigger_backend=None
    ) -> None:
        self._core = core
        self._project_id = project_id
        self._project_root = project_root
        self._principal = principal
        self._schedules: dict[str, _Schedule] = {}
        self._history: dict[str, list[TaskRecord]] = {}
        self._trigger_backend = trigger_backend

    def create(self, schedule_id: str, call: CapabilityCall, *, trigger: str | None = None) -> None:
        self._schedules[schedule_id] = _Schedule(call=call.model_copy(update={
            "project_root": self._project_root,
            "schedule_id": schedule_id,
        }))
        if trigger is not None:
            if self._trigger_backend is None:
                raise RuntimeError("scheduled trigger backend is unavailable")
            self._trigger_backend.add(schedule_id, trigger, lambda run_id: self.trigger(schedule_id, run_id))

    def enable(self, schedule_id: str) -> None:
        self._schedules[schedule_id].enabled = True

    def disable(self, schedule_id: str) -> None:
        self._schedules[schedule_id].enabled = False

    async def trigger(self, schedule_id: str, run_id: str) -> TaskRecord:
        schedule = self._schedules[schedule_id]
        if not schedule.enabled:
            raise PermissionError("schedule is disabled")
        task_id = f"schedule-{schedule_id}-{run_id}"
        record = await self._core.submit(TaskCommand(
            command_id=f"schedule-command-{schedule_id}-{run_id}",
            task_id=task_id,
            thread_id=f"schedule:{schedule_id}",
            project_id=self._project_id,
            command_type="schedule.trigger",
            payload=schedule.call.model_dump(mode="json"),
        ), principal=self._principal, trusted_schedule_id=schedule_id)
        history = self._history.setdefault(schedule_id, [])
        if all(item.task_id != record.task_id for item in history):
            history.append(record)
        return record

    async def recover_missed(self, schedule_id: str, run_id: str) -> TaskRecord:
        return await self.trigger(schedule_id, run_id)

    def history(self, schedule_id: str) -> tuple[TaskRecord, ...]:
        return tuple(self._history.get(schedule_id, ()))


class ApschedulerTriggerBackend:
    def __init__(self, scheduler=None) -> None:
        if scheduler is None:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
            except ImportError as error:
                raise RuntimeError("APScheduler is not installed in this provider environment") from error
            scheduler = AsyncIOScheduler()
        self._scheduler = scheduler

    def add(self, schedule_id: str, trigger: str, callback) -> None:
        if not trigger.startswith("cron:"):
            raise ValueError("APScheduler trigger must use cron:<expression>")
        try:
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as error:
            raise RuntimeError("APScheduler is not installed in this provider environment") from error
        cron = CronTrigger.from_crontab(trigger.removeprefix("cron:"))

        async def run() -> None:
            await callback(str(uuid7()))

        self._scheduler.add_job(run, cron, id=schedule_id, replace_existing=True, coalesce=True)
