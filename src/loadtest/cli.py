"""CLI entry point — argparse wiring."""
from __future__ import annotations

import asyncio
import sys

import argparse

from loadtest.report import format_json, format_table
from loadtest.runner import run
from loadtest.stats import compute_stats


def _parse_header(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise argparse.ArgumentTypeError(
            f"Header must be in 'Key: Value' format, got: {value!r}"
        )
    key, _, val = value.partition(":")
    return key.strip(), val.strip()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="loadtest",
        description="Async HTTP load tester — measures latency percentiles, throughput, error rates.",
    )
    p.add_argument("url", help="Target URL")
    p.add_argument("-n", "--requests", type=int, default=100, metavar="N",
                   help="Total number of requests (default: 100)")
    p.add_argument("-c", "--concurrency", type=int, default=10, metavar="C",
                   help="Max in-flight requests (default: 10)")
    p.add_argument("-m", "--method", default="GET", metavar="METHOD",
                   help="HTTP method (default: GET)")
    p.add_argument("-t", "--timeout", type=float, default=30.0, metavar="SECS",
                   help="Per-request timeout in seconds (default: 30)")
    p.add_argument("-H", "--header", dest="headers", action="append",
                   default=[], metavar="KEY:VALUE",
                   help="Request header, repeatable")
    p.add_argument("--body", default=None,
                   help="Request body string")
    p.add_argument("--json", action="store_true",
                   help="Output results as JSON")
    return p


def _validate(args: argparse.Namespace) -> None:
    errors: list[str] = []
    if args.requests <= 0:
        errors.append(f"--requests must be > 0, got {args.requests}")
    if args.concurrency <= 0:
        errors.append(f"--concurrency must be > 0, got {args.concurrency}")
    if args.concurrency > args.requests:
        errors.append(
            f"--concurrency ({args.concurrency}) must be <= --requests ({args.requests})"
        )
    if args.timeout <= 0:
        errors.append(f"--timeout must be > 0, got {args.timeout}")
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    _validate(args)

    headers: dict[str, str] = {}
    for raw in args.headers:
        try:
            k, v = _parse_header(raw)
            headers[k] = v
        except argparse.ArgumentTypeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)

    results, elapsed, _ = asyncio.run(
        run(
            url=args.url,
            n_requests=args.requests,
            concurrency=args.concurrency,
            method=args.method.upper(),
            timeout_s=args.timeout,
            headers=headers or None,
            body=args.body,
        )
    )

    stats = compute_stats(results, elapsed)

    if args.json:
        print(format_json(stats))
    else:
        print(format_table(stats))


if __name__ == "__main__":
    main()
