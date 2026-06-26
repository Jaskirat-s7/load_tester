"""Format Stats into human-readable table or JSON."""
from __future__ import annotations

import json

from loadtest.stats import Stats


def format_table(s: Stats) -> str:
    lines: list[str] = []
    w = 22  # label column width

    def row(label: str, value: str) -> str:
        return f"  {label:<{w}}{value}"

    lines.append("")
    lines.append("=" * 50)
    lines.append("  Load Test Results")
    lines.append("=" * 50)

    lines.append(row("Total requests:", str(s.total)))
    lines.append(row("Succeeded:", str(s.succeeded)))
    lines.append(row("Failed:", str(s.failed)))
    lines.append(row("Throughput:", f"{s.throughput_rps:.2f} req/s"))

    lines.append("")
    lines.append("  Latency (ms):")
    lines.append(row("  min:", f"{s.latency_min:.2f}"))
    lines.append(row("  mean:", f"{s.latency_mean:.2f}"))
    lines.append(row("  p50:", f"{s.latency_p50:.2f}"))
    lines.append(row("  p90:", f"{s.latency_p90:.2f}"))
    lines.append(row("  p95:", f"{s.latency_p95:.2f}"))
    lines.append(row("  p99:", f"{s.latency_p99:.2f}"))
    lines.append(row("  max:", f"{s.latency_max:.2f}"))

    if s.error_breakdown:
        lines.append("")
        lines.append("  Errors:")
        for error_type, count in sorted(s.error_breakdown.items()):
            lines.append(row(f"  {error_type}:", str(count)))

    lines.append("=" * 50)
    lines.append("")
    return "\n".join(lines)


def format_json(s: Stats) -> str:
    data = {
        "total": s.total,
        "succeeded": s.succeeded,
        "failed": s.failed,
        "throughput_rps": round(s.throughput_rps, 4),
        "latency_ms": {
            "min": round(s.latency_min, 4),
            "mean": round(s.latency_mean, 4),
            "p50": round(s.latency_p50, 4),
            "p90": round(s.latency_p90, 4),
            "p95": round(s.latency_p95, 4),
            "p99": round(s.latency_p99, 4),
            "max": round(s.latency_max, 4),
        },
        "error_breakdown": s.error_breakdown,
    }
    return json.dumps(data, indent=2)
