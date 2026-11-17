from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model_run_normalizer import capture_original_output, normalize_model_result
from .model_run_store import ModelRunStore
from .models import CanonicalModelResult, CanonicalModelRun, ModelInputManifest, ModelRunCreateRequest, ModelTiming


JURY_CRITERIA = (
    "Score the submitted code from 1 to 10. Identify concrete correctness, security, maintainability, "
    "and testability issues. Return evidence from the supplied content and do not assume unavailable tools."
)


class ModelRunService:
    def __init__(
        self,
        store: ModelRunStore,
        inference: Any,
        workspace: Any,
        context: Any,
        *,
        concurrency: int = 2,
    ) -> None:
        self.store = store
        self.inference = inference
        self.workspace = workspace
        self.context = context
        self.semaphore = asyncio.Semaphore(concurrency)
        self._cancelled: set[str] = set()

    async def create(self, request: ModelRunCreateRequest) -> CanonicalModelRun:
        models = await self.inference.list_models()
        roster = [item["name"] for item in models if item.get("installed")]
        unavailable = [item["name"] for item in models if not item.get("installed")]
        run = self.store.create(request, roster, request.request_key)
        if run.unavailable_models != unavailable:
            run = self.store.update_run(run.model_copy(update={"unavailable_models": unavailable}))
        return run

    async def run(self, run_id: str) -> None:
        run = self.store.get(run_id)
        await asyncio.gather(*(self._run_model(run, result) for result in run.results))

    async def _run_model(self, run: CanonicalModelRun, queued: CanonicalModelResult) -> None:
        async with self.semaphore:
            current = self.store.get(run.run_id)
            matching = next(item for item in current.results if item.result_id == queued.result_id)
            if matching.status != "queued" or run.run_id in self._cancelled:
                return
            started = datetime.now(timezone.utc)
            running = matching.model_copy(update={
                "status": "running",
                "timing": ModelTiming(started_at=started, duration_ms=0),
            })
            self.store.update_result(run.run_id, running)
            try:
                session = self.workspace.get_session(run.session_id)
                vision = await self.inference.supports_vision(queued.requested_model)
                prompt, images, manifest = self.context.build_for_model(session, run.prompt, vision)
                if not isinstance(manifest, ModelInputManifest):
                    manifest = ModelInputManifest.model_validate(manifest)
                if run.profile == "code_jury":
                    prompt = f"CODE JURY CRITERIA:\n{JURY_CRITERIA}\n\n{prompt}"
                result = await self.inference.chat(queued.requested_model, prompt, images=images)
                original = capture_original_output(
                    output_id=uuid.uuid4().hex,
                    model=queued.requested_model,
                    content=result.content,
                    reasoning_entries=result.reasoning.entries if result.reasoning else [],
                    provider_events=[],
                )
                self.store.append_original(run.run_id, queued.result_id, original)
                completed = datetime.now(timezone.utc)
                normalized = normalize_model_result(
                    original,
                    result,
                    warnings=list(manifest.omitted_modalities),
                    timing=ModelTiming(
                        started_at=started,
                        completed_at=completed,
                        duration_ms=max(0, int((completed - started).total_seconds() * 1000)),
                    ),
                ).model_copy(update={
                    "result_id": queued.result_id,
                    "requested_model": queued.requested_model,
                    "input_manifest": manifest,
                })
                self.store.update_result(run.run_id, normalized)
            except Exception as error:
                completed = datetime.now(timezone.utc)
                original = capture_original_output(
                    output_id=uuid.uuid4().hex,
                    model=queued.requested_model,
                    content="",
                    reasoning_entries=[],
                    provider_events=[{"type": "error", "message": str(error)}],
                )
                self.store.append_original(run.run_id, queued.result_id, original)
                failed = queued.model_copy(update={
                    "status": "failed",
                    "timing": ModelTiming(
                        started_at=started,
                        completed_at=completed,
                        duration_ms=max(0, int((completed - started).total_seconds() * 1000)),
                    ),
                    "original_output_id": original.output_id,
                    "original_output_digest": original.digest,
                    "error_code": "provider_error",
                    "error_message": str(error),
                })
                self.store.update_result(run.run_id, failed)

    def cancel(self, run_id: str) -> CanonicalModelRun:
        self._cancelled.add(run_id)
        return self.store.request_cancel(run_id)

    def get(self, run_id: str) -> CanonicalModelRun:
        return self.store.get(run_id)

    async def recover_incomplete_runs(self) -> None:
        now = datetime.now(timezone.utc)
        for run in self.store.list_runs():
            if run.status not in {"queued", "running"}:
                continue
            for result in run.results:
                if result.status not in {"queued", "running"}:
                    continue
                failed = result.model_copy(update={
                    "status": "failed",
                    "timing": result.timing.model_copy(update={"completed_at": now}),
                    "error_code": "server_restart",
                    "error_message": "The server restarted before this model completed",
                })
                self.store.update_result(run.run_id, failed)
