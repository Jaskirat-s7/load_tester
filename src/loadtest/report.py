"""Format Stats into a human-readable table or JSON. No computation here."""
from __future__ import annotations

import json

from loadtest.stats import Stats


def format_table(s: Stats) -> str:
    w = 22  # label column width
    lines: list[str] = []

    def row(label: str, value: str) -> str:
        return f"  {label:<{w}}{value}"

    lines.append("")
    lines.append("=" * 50)
    lines.append("  Load Test Results")
    lines.append("=" * 50)

    lines.append(row("Total requests:", str(s.total)))
    lines.append(row("Succeeded (2xx):", str(s.succeeded)))
    lines.append(row("Failed:", str(s.failed)))
    lines.append(row("Throughput:", f"{s.throughput_rps:.2f} req/s"))

    lines.append("")
    if s.latency is None:
        lines.append(f"  Latency: no HTTP responses received ({s.total} requests all failed)")
    else:
        lat = s.latency
        lines.append(f"  Latency (ms) — over {s.responded} responded request(s):")
        lines.append(row("  min:", f"{lat.min:.2f}"))
        lines.append(row("  mean:", f"{lat.mean:.2f}"))
        lines.append(row("  p50:", f"{lat.p50:.2f}"))
        lines.append(row("  p90:", f"{lat.p90:.2f}"))
        lines.append(row("  p95:", f"{lat.p95:.2f}"))
        lines.append(row("  p99:", f"{lat.p99:.2f}"))
        lines.append(row("  max:", f"{lat.max:.2f}"))

    if s.error_breakdown:
        lines.append("")
        lines.append("  Errors:")
        for error_type, count in sorted(s.error_breakdown.items()):
            lines.append(row(f"  {error_type}:", str(count)))

    lines.append("=" * 50)
    lines.append("")
    return "\n".join(lines)


def format_json(s: Stats) -> str:
    latency = None
    if s.latency is not None:
        latency = {
            "min": round(s.latency.min, 4),
            "mean": round(s.latency.mean, 4),
            "p50": round(s.latency.p50, 4),
            "p90": round(s.latency.p90, 4),
            "p95": round(s.latency.p95, 4),
            "p99": round(s.latency.p99, 4),
            "max": round(s.latency.max, 4),
        }
    data = {
        "total": s.total,
        "succeeded": s.succeeded,
        "failed": s.failed,
        "responded": s.responded,
        "throughput_rps": round(s.throughput_rps, 4),
        "latency_ms": latency,
        "error_breakdown": s.error_breakdown,
    }
    return json.dumps(data, indent=2)
