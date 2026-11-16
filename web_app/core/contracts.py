from __future__ import annotations

from enum import Enum
from typing import Any, NewType

from pydantic import BaseModel, ConfigDict, Field


TaskId = NewType("TaskId", str)
ThreadId = NewType("ThreadId", str)
ProjectId = NewType("ProjectId", str)


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    interrupted = "interrupted"


class ExecutionMode(str, Enum):
    native = "native"
    brokered = "brokered"


class FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True)


class RuntimeIdentity(FrozenContract):
    platform: str = Field(min_length=1)
    runtime_ids: tuple[str, ...] = ()
    model_ids: tuple[str, ...] = ()
    granted_permissions: tuple[str, ...] = ()
    installed_packages: tuple[str, ...] = ()


class CapabilityManifest(FrozenContract):
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
    implementation_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
    version: str = Field(min_length=1)
    modes: tuple[ExecutionMode, ...] = (ExecutionMode.native,)
    platforms: tuple[str, ...] = ()
    runtime_requirements: tuple[str, ...] = ()
    native_models: tuple[str, ...] = ()
    brokered_models: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    required_packages: tuple[str, ...] = ()


class CapabilityResult(FrozenContract):
    capability_id: str
    implementation_id: str
    runnable: bool
    reason: str | None = None


class TaskCommand(FrozenContract):
    task_id: TaskId
    thread_id: ThreadId
    project_id: ProjectId
    command_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskEvent(FrozenContract):
    task_id: TaskId
    sequence: int = Field(ge=0)
    event_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(FrozenContract):
    task_id: TaskId
    thread_id: ThreadId
    project_id: ProjectId
    status: TaskStatus = TaskStatus.pending
    events: tuple[TaskEvent, ...] = ()
