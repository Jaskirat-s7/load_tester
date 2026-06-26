"""Unit tests for report.py formatting."""
import json

from loadtest.report import format_json, format_table
from loadtest.stats import LatencyStats, Stats


def _stats(with_latency: bool = True) -> Stats:
    latency = (
        LatencyStats(min=1.0, mean=2.0, p50=2.0, p90=3.0, p95=3.5, p99=4.0, max=5.0)
        if with_latency
        else None
    )
    return Stats(
        total=10,
        succeeded=8,
        failed=2,
        responded=9,
        throughput_rps=12.345,
        latency=latency,
        error_breakdown={"non_2xx": 1, "timeout": 1},
    )


class TestTable:
    def test_contains_core_numbers(self):
        out = format_table(_stats())
        assert "Total requests:" in out
        assert "p99:" in out
        assert "12.35 req/s" in out  # rounded to 2dp
        assert "non_2xx:" in out

    def test_no_latency_message(self):
        out = format_table(_stats(with_latency=False))
        assert "no HTTP responses received" in out
        assert "p99:" not in out


class TestJson:
    def test_roundtrips_and_has_fields(self):
        out = format_json(_stats())
        data = json.loads(out)
        assert data["total"] == 10
        assert data["responded"] == 9
        assert data["latency_ms"]["p99"] == 4.0
        assert data["error_breakdown"] == {"non_2xx": 1, "timeout": 1}

    def test_null_latency_when_no_responses(self):
        data = json.loads(format_json(_stats(with_latency=False)))
        assert data["latency_ms"] is None
