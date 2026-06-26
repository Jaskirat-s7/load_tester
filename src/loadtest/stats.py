"""
Pure statistics functions — no I/O, no async, trivially unit-testable.

Why tail percentiles matter more than the average
-------------------------------------------------
The mean collapses an entire distribution into one number, and latency
distributions are almost always right-skewed with a long tail. A service where
99% of requests finish in 10 ms but 1% take 5 s has a flattering mean yet a
terrible experience for everyone who hits the tail. p95/p99 expose that worst
slice — the one real users repeatedly run into — so they, not the average, are
what SLOs, timeout budgets, and capacity planning should be calibrated against.

Which requests count toward latency
-----------------------------------
Latency percentiles are computed ONLY over requests that received an HTTP
response (any status, including non-2xx — those are real responses with real
server timing). Timeouts and connection errors are deliberately excluded: a
timeout's measured latency is just the timeout ceiling, and a refused
connection is ~0 ms; mixing either into the distribution would distort it.
Those failures are still counted in totals and in the error breakdown.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class RequestResult:
    latency_ms: float           # wall-clock time including body read
    status_code: int | None     # None when no HTTP response was received
    success: bool               # True for 2xx status codes
    error_type: str | None      # "timeout" | "connection_error" | "non_2xx" | "error" | None

    @property
    def responded(self) -> bool:
        """True if an HTTP response (any status) came back — i.e. latency is meaningful."""
        return self.status_code is not None


@dataclass
class LatencyStats:
    """Latency summary in milliseconds, over responded requests only."""
    min: float
    mean: float
    p50: float
    p90: float
    p95: float
    p99: float
    max: float


@dataclass
class Stats:
    total: int
    succeeded: int                  # 2xx
    failed: int                     # everything else (non-2xx + transport errors)
    responded: int                  # received any HTTP response (latency population)
    throughput_rps: float           # total requests / wall-clock seconds
    latency: LatencyStats | None    # None when no request received a response
    error_breakdown: dict[str, int] = field(default_factory=dict)


def percentile(sorted_values: list[float], p: float) -> float:
    """
    Nearest-rank percentile on an ascending-sorted list.

    The nearest-rank method maps the p-th percentile to the 0-based index
        i = ceil(p/100 * n) - 1     clamped to [0, n-1]
    and returns an actual observed data point (no interpolation), which is the
    most interpretable choice for latency reporting. Input must be pre-sorted.
    """
    if not sorted_values:
        raise ValueError("Cannot compute percentile of empty list")
    n = len(sorted_values)
    idx = max(0, math.ceil(p / 100 * n) - 1)
    return sorted_values[idx]


def compute_latency_stats(latencies_ms: Sequence[float]) -> LatencyStats:
    """Summarise a non-empty sequence of latencies (ms)."""
    if not latencies_ms:
        raise ValueError("Cannot compute latency stats over an empty sequence")
    s = sorted(latencies_ms)
    return LatencyStats(
        min=s[0],
        mean=sum(s) / len(s),
        p50=percentile(s, 50),
        p90=percentile(s, 90),
        p95=percentile(s, 95),
        p99=percentile(s, 99),
        max=s[-1],
    )


def compute_stats(results: Sequence[RequestResult], wall_clock_seconds: float) -> Stats:
    """Aggregate a sequence of RequestResult into a Stats summary."""
    if not results:
        raise ValueError("No results to aggregate")

    succeeded = sum(1 for r in results if r.success)
    responded_latencies = [r.latency_ms for r in results if r.responded]

    error_breakdown: dict[str, int] = {}
    for r in results:
        if r.error_type:
            error_breakdown[r.error_type] = error_breakdown.get(r.error_type, 0) + 1

    throughput = len(results) / wall_clock_seconds if wall_clock_seconds > 0 else 0.0
    latency = compute_latency_stats(responded_latencies) if responded_latencies else None

    return Stats(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        responded=len(responded_latencies),
        throughput_rps=throughput,
        latency=latency,
        error_breakdown=error_breakdown,
    )
