"""Unit tests for stats.py — pure functions, no I/O."""
import pytest

from loadtest.stats import (
    RequestResult,
    compute_latency_stats,
    compute_stats,
    percentile,
)


# ---------------------------------------------------------------------------
# percentile() — nearest-rank method, hand-computed expected values
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_single_value(self):
        assert percentile([42.0], 50) == 42.0
        assert percentile([42.0], 99) == 42.0
        assert percentile([42.0], 0) == 42.0

    def test_all_equal(self):
        vals = [7.0] * 10
        for p in (0, 50, 90, 99, 100):
            assert percentile(vals, p) == 7.0

    def test_two_values(self):
        vals = [1.0, 2.0]
        # p50: ceil(0.50*2)-1 = ceil(1.0)-1 = 0 → vals[0] = 1.0
        assert percentile(vals, 50) == 1.0
        # p99: ceil(0.99*2)-1 = ceil(1.98)-1 = 1 → vals[1] = 2.0
        assert percentile(vals, 99) == 2.0

    def test_ten_values(self):
        # [10, 20, ..., 100]
        vals = [float(i * 10) for i in range(1, 11)]
        # p50: ceil(0.50*10)-1 = 4 → 50
        assert percentile(vals, 50) == 50.0
        # p90: ceil(0.90*10)-1 = 8 → 90
        assert percentile(vals, 90) == 90.0
        # p99: ceil(0.99*10)-1 = 9 → 100
        assert percentile(vals, 99) == 100.0

    def test_hand_computed_seven_values(self):
        # vals = [2, 4, 6, 8, 10, 12, 14], n = 7
        vals = [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0]
        # p50: ceil(0.50*7)-1 = ceil(3.5)-1 = 3 → vals[3] = 8
        assert percentile(vals, 50) == 8.0
        # p75: ceil(0.75*7)-1 = ceil(5.25)-1 = 5 → vals[5] = 12
        assert percentile(vals, 75) == 12.0
        # p90: ceil(0.90*7)-1 = ceil(6.3)-1 = 6 → vals[6] = 14
        assert percentile(vals, 90) == 14.0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            percentile([], 50)


# ---------------------------------------------------------------------------
# compute_latency_stats()
# ---------------------------------------------------------------------------

class TestComputeLatencyStats:
    def test_single(self):
        lat = compute_latency_stats([100.0])
        assert lat.min == lat.max == lat.mean == lat.p50 == lat.p99 == 100.0

    def test_all_equal(self):
        lat = compute_latency_stats([50.0] * 20)
        assert lat.min == lat.max == lat.mean == lat.p99 == 50.0

    def test_known_list(self):
        lat = compute_latency_stats([float(i * 10) for i in range(1, 11)])
        assert lat.min == 10.0
        assert lat.max == 100.0
        assert lat.mean == pytest.approx(55.0)
        assert lat.p50 == 50.0
        assert lat.p90 == 90.0
        assert lat.p99 == 100.0

    def test_unsorted_input_is_sorted(self):
        lat = compute_latency_stats([30.0, 10.0, 20.0])
        assert lat.min == 10.0
        assert lat.max == 30.0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_latency_stats([])


# ---------------------------------------------------------------------------
# compute_stats()
# ---------------------------------------------------------------------------

def _ok(latency_ms: float, status: int = 200) -> RequestResult:
    return RequestResult(latency_ms=latency_ms, status_code=status,
                         success=200 <= status < 300,
                         error_type=None if 200 <= status < 300 else "non_2xx")

def _fail(latency_ms: float, error_type: str) -> RequestResult:
    return RequestResult(latency_ms=latency_ms, status_code=None,
                         success=False, error_type=error_type)


class TestComputeStats:
    def test_single_success(self):
        s = compute_stats([_ok(100.0)], wall_clock_seconds=1.0)
        assert (s.total, s.succeeded, s.failed, s.responded) == (1, 1, 0, 1)
        assert s.latency is not None
        assert s.latency.min == s.latency.max == 100.0
        assert s.throughput_rps == pytest.approx(1.0)

    def test_counts_and_error_breakdown(self):
        results = [_ok(10.0)] * 3 + [_fail(20.0, "timeout")] * 2
        s = compute_stats(results, wall_clock_seconds=1.0)
        assert (s.total, s.succeeded, s.failed) == (5, 3, 2)
        assert s.error_breakdown == {"timeout": 2}

    def test_mixed_error_types(self):
        results = [
            _fail(5.0, "timeout"),
            _fail(5.0, "timeout"),
            _fail(5.0, "connection_error"),
            _ok(5.0),
        ]
        s = compute_stats(results, wall_clock_seconds=0.5)
        assert s.error_breakdown == {"timeout": 2, "connection_error": 1}

    def test_non_2xx_is_failed_but_counts_toward_latency(self):
        # A 500 is a failure, but it IS a real response with real timing.
        results = [_ok(10.0, status=200), _ok(999.0, status=500)]
        s = compute_stats(results, wall_clock_seconds=1.0)
        assert s.succeeded == 1
        assert s.failed == 1
        assert s.responded == 2
        assert s.error_breakdown == {"non_2xx": 1}
        # latency population includes the 500
        assert s.latency is not None
        assert s.latency.max == 999.0

    def test_failures_excluded_from_latency_population(self):
        # The crux of the measurement-correctness fix: a timeout's bogus
        # latency must NOT pollute the percentiles.
        results = [_ok(10.0), _ok(20.0), _fail(30000.0, "timeout"), _fail(0.1, "connection_error")]
        s = compute_stats(results, wall_clock_seconds=1.0)
        assert s.responded == 2
        assert s.latency is not None
        # Only 10 and 20 count — the 30000ms timeout and 0.1ms refusal are gone.
        assert s.latency.min == 10.0
        assert s.latency.max == 20.0
        assert s.latency.mean == pytest.approx(15.0)

    def test_all_failed_yields_no_latency(self):
        results = [_fail(0.1, "connection_error") for _ in range(5)]
        s = compute_stats(results, wall_clock_seconds=1.0)
        assert s.total == 5
        assert s.succeeded == 0
        assert s.responded == 0
        assert s.latency is None
        assert s.error_breakdown == {"connection_error": 5}

    def test_throughput_uses_total_requests(self):
        results = [_ok(1.0)] * 100
        s = compute_stats(results, wall_clock_seconds=4.0)
        assert s.throughput_rps == pytest.approx(25.0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_stats([], wall_clock_seconds=1.0)
