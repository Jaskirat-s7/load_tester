"""Unit tests for stats.py — pure functions, no I/O."""
import math
import pytest

from loadtest.stats import RequestResult, Stats, compute_stats, percentile


# ---------------------------------------------------------------------------
# percentile() — nearest-rank method
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_single_value(self):
        assert percentile([42.0], 50) == 42.0
        assert percentile([42.0], 99) == 42.0

    def test_all_equal(self):
        vals = [7.0] * 10
        for p in (0, 50, 90, 99, 100):
            assert percentile(vals, p) == 7.0

    def test_two_values(self):
        vals = [1.0, 2.0]
        # p50: ceil(0.5*2)-1 = ceil(1)-1 = 0 → vals[0] = 1.0
        assert percentile(vals, 50) == 1.0
        # p99: ceil(0.99*2)-1 = ceil(1.98)-1 = 2-1 = 1 → vals[1] = 2.0
        assert percentile(vals, 99) == 2.0

    def test_ten_values_p90(self):
        # [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        # p90: ceil(0.9*10)-1 = ceil(9)-1 = 9-1 = 8 → vals[8] = 90
        vals = [float(i * 10) for i in range(1, 11)]
        assert percentile(vals, 90) == 90.0

    def test_ten_values_p99(self):
        # p99: ceil(0.99*10)-1 = ceil(9.9)-1 = 10-1 = 9 → vals[9] = 100
        vals = [float(i * 10) for i in range(1, 11)]
        assert percentile(vals, 99) == 100.0

    def test_ten_values_p50(self):
        # p50: ceil(0.5*10)-1 = ceil(5)-1 = 5-1 = 4 → vals[4] = 50
        vals = [float(i * 10) for i in range(1, 11)]
        assert percentile(vals, 50) == 50.0

    def test_hand_computed_seven_values(self):
        # Explicit hand-computation to document the method
        # vals = [2, 4, 6, 8, 10, 12, 14]   n=7
        vals = [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0]
        # p50: ceil(0.50*7)-1 = ceil(3.5)-1 = 4-1 = 3 → vals[3] = 8
        assert percentile(vals, 50) == 8.0
        # p75: ceil(0.75*7)-1 = ceil(5.25)-1 = 6-1 = 5 → vals[5] = 12
        assert percentile(vals, 75) == 12.0
        # p90: ceil(0.90*7)-1 = ceil(6.3)-1  = 7-1 = 6 → vals[6] = 14
        assert percentile(vals, 90) == 14.0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            percentile([], 50)


# ---------------------------------------------------------------------------
# compute_stats()
# ---------------------------------------------------------------------------

def _make_ok(latency_ms: float) -> RequestResult:
    return RequestResult(latency_ms=latency_ms, status_code=200, success=True, error_type=None)

def _make_fail(latency_ms: float, error_type: str) -> RequestResult:
    return RequestResult(latency_ms=latency_ms, status_code=None, success=False, error_type=error_type)


class TestComputeStats:
    def test_single_success(self):
        results = [_make_ok(100.0)]
        s = compute_stats(results, wall_clock_seconds=1.0)
        assert s.total == 1
        assert s.succeeded == 1
        assert s.failed == 0
        assert s.latency_min == 100.0
        assert s.latency_max == 100.0
        assert s.latency_mean == 100.0
        assert s.latency_p50 == 100.0
        assert s.latency_p99 == 100.0
        assert s.throughput_rps == pytest.approx(1.0)

    def test_all_equal(self):
        results = [_make_ok(50.0) for _ in range(20)]
        s = compute_stats(results, wall_clock_seconds=2.0)
        assert s.latency_min == 50.0
        assert s.latency_max == 50.0
        assert s.latency_mean == 50.0
        assert s.latency_p99 == 50.0
        assert s.throughput_rps == pytest.approx(10.0)

    def test_counts_failures(self):
        results = [_make_ok(10.0)] * 3 + [_make_fail(20.0, "timeout")] * 2
        s = compute_stats(results, wall_clock_seconds=1.0)
        assert s.total == 5
        assert s.succeeded == 3
        assert s.failed == 2
        assert s.error_breakdown == {"timeout": 2}

    def test_mixed_error_types(self):
        results = [
            _make_fail(5.0, "timeout"),
            _make_fail(5.0, "timeout"),
            _make_fail(5.0, "connection_error"),
            _make_ok(5.0),
        ]
        s = compute_stats(results, wall_clock_seconds=0.5)
        assert s.error_breakdown == {"timeout": 2, "connection_error": 1}

    def test_latency_percentiles_known_list(self):
        # 10 values: [10, 20, ..., 100] ms — hand-checked above
        results = [_make_ok(float(i * 10)) for i in range(1, 11)]
        s = compute_stats(results, wall_clock_seconds=1.0)
        assert s.latency_min == 10.0
        assert s.latency_max == 100.0
        assert s.latency_mean == pytest.approx(55.0)
        assert s.latency_p50 == 50.0
        assert s.latency_p90 == 90.0
        assert s.latency_p99 == 100.0

    def test_throughput(self):
        results = [_make_ok(1.0)] * 100
        s = compute_stats(results, wall_clock_seconds=4.0)
        assert s.throughput_rps == pytest.approx(25.0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_stats([], wall_clock_seconds=1.0)
