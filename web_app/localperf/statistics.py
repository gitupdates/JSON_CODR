from __future__ import annotations

import random
import statistics
from statistics import NormalDist

from web_app.localperf.models import SampleRecord


def compare_sample_sets(baseline: list[SampleRecord], candidate: list[SampleRecord], *, resamples: int = 10_000, seed: int = 20261115) -> dict:
    base = {(item.prompt_id, item.repetition): item.generation_tokens_per_second for item in baseline}
    other = {(item.prompt_id, item.repetition): item.generation_tokens_per_second for item in candidate}
    if set(base) != set(other) or not base:
        raise ValueError("Paired comparisons require identical prompt and repetition samples")
    keys = sorted(base)
    changes = [(other[key] - base[key]) / base[key] for key in keys]
    rng = random.Random(seed)
    estimates = []
    for _ in range(resamples):
        draw = [changes[rng.randrange(len(changes))] for _ in changes]
        estimates.append(statistics.fmean(draw))
    estimates.sort()
    observed = statistics.fmean(changes)
    normal = NormalDist()
    below = min(max(sum(value < observed for value in estimates) / resamples, 1 / (2 * resamples)), 1 - 1 / (2 * resamples))
    bias = normal.inv_cdf(below)
    jackknife = [statistics.fmean(changes[:index] + changes[index + 1:]) for index in range(len(changes))] if len(changes) > 1 else [observed]
    jack_mean = statistics.fmean(jackknife)
    numerator = sum((jack_mean - value) ** 3 for value in jackknife)
    denominator = 6 * sum((jack_mean - value) ** 2 for value in jackknife) ** 1.5
    acceleration = numerator / denominator if denominator else 0
    def adjusted(alpha: float) -> float:
        z = normal.inv_cdf(alpha)
        value = normal.cdf(bias + (bias + z) / (1 - acceleration * (bias + z)))
        return min(max(value, 0), 1)
    lower = estimates[round(adjusted(.025) * (resamples - 1))]
    upper = estimates[round(adjusted(.975) * (resamples - 1))]
    return {
        "relative_change": round(observed, 12),
        "confidence_interval": [lower, upper],
        "probability_superior": sum(value > 0 for value in estimates) / resamples,
        "paired_samples": len(keys),
        "method": "seeded_stratified_paired_bootstrap_bca",
        "resamples": resamples,
    }
