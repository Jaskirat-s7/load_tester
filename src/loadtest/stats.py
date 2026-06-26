"""
Pure statistics functions — no I/O, no async.

Why tail percentiles matter more than the average
-------------------------------------------------
The mean hides the distribution. A benchmark where 99% of requests finish in
10 ms but 1% take 5 s has a "good" mean yet terrible user experience for those
who hit the tail. p95/p99 expose the worst slice that real users regularly
encounter, making them the primary signal for capacity and SLO decisions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class RequestResult:
    latency_ms: float           # wall-clock time including body read
    status_code: int | None     # None when a network error prevented a response
    success: bool               # True for 2xx status codes
    error_type: str | None      # "timeout" | "connection_error" | "non_2xx" | None


@dataclass
class Stats:
    total: int
    succeeded: int
    failed: int
    # latency (ms) — only over successful+failed-with-latency requests
    latency_min: float
    latency_mean: float
    latency_p50: float
    latency_p90: float
    latency_p95: float
    latency_p99: float
    latency_max: float
    throughput_rps: float           # total requests / wall-clock seconds
    error_breakdown: dict[str, int] = field(default_factory=dict)


def percentile(sorted_values: list[float], p: float) -> float:
    """
    Nearest-rank percentile on a sorted list.

    The nearest-rank method maps the p-th percentile to index
        i = ceil(p/100 * n) - 1   (0-based)
    clamped to [0, n-1]. It requires the input to be sorted ascending and
    returns an actual data point (no interpolation), which is the most
    interpretable choice for latency reporting.
    """
    if not sorted_values:
        raise ValueError("Cannot compute percentile of empty list")
    n = len(sorted_values)
    idx = max(0, math.ceil(p / 100 * n) - 1)
    return sorted_values[idx]


def compute_stats(results: Sequence[RequestResult], wall_clock_seconds: float) -> Stats:
    """Aggregate a sequence of RequestResult into a Stats summary."""
    if not results:
        raise ValueError("No results to aggregate")

    latencies = sorted(r.latency_ms for r in results)
    succeeded = sum(1 for r in results if r.success)
    failed = len(results) - succeeded

    error_breakdown: dict[str, int] = {}
    for r in results:
        if r.error_type:
            error_breakdown[r.error_type] = error_breakdown.get(r.error_type, 0) + 1

    mean = sum(latencies) / len(latencies)
    throughput = len(results) / wall_clock_seconds if wall_clock_seconds > 0 else 0.0

    return Stats(
        total=len(results),
        succeeded=succeeded,
        failed=failed,
        latency_min=latencies[0],
        latency_mean=mean,
        latency_p50=percentile(latencies, 50),
        latency_p90=percentile(latencies, 90),
        latency_p95=percentile(latencies, 95),
        latency_p99=percentile(latencies, 99),
        latency_max=latencies[-1],
        throughput_rps=throughput,
        error_breakdown=error_breakdown,
    )
