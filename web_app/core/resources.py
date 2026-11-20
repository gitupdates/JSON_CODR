from __future__ import annotations

from web_app.core.contracts import FrozenContract


class ResourceSample(FrozenContract):
    active_tasks: int
    vram_mb: int


class ResourceDecision(FrozenContract):
    allowed: bool
    reason: str


class ResourceBudget:
    def __init__(self, max_concurrency: int, max_vram_mb: int) -> None:
        if max_concurrency < 1 or max_vram_mb < 0:
            raise ValueError("resource limits must be non-negative and allow at least one task")
        self.max_concurrency = max_concurrency
        self.max_vram_mb = max_vram_mb

    def evaluate(self, sample: ResourceSample) -> ResourceDecision:
        if sample.active_tasks >= self.max_concurrency:
            return ResourceDecision(allowed=False, reason="local concurrency limit reached")
        if sample.vram_mb > self.max_vram_mb:
            return ResourceDecision(allowed=False, reason="local VRAM budget exceeded")
        return ResourceDecision(allowed=True, reason="within local resource budget")
