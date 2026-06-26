"""Async load-test engine.

Concurrency model
-----------------
A single asyncio.Semaphore with size == concurrency bounds the number of
requests in flight at any moment. Tasks are created all at once (so scheduling
overhead is amortised), but each task must acquire the semaphore before issuing
the HTTP call and releases it immediately after — guaranteeing the in-flight
count never exceeds the limit even if aiohttp's own connection pool is wider.

Connection pooling
------------------
One aiohttp.ClientSession is shared across all tasks. The session's connector
is sized to match --concurrency so keep-alive connections aren't wasted and
the OS file-descriptor count stays bounded.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

import aiohttp

from loadtest.stats import RequestResult


async def _single_request(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    method: str,
    url: str,
    timeout: aiohttp.ClientTimeout,
    body: str | None,
    in_flight_counter: list[int],  # mutable [current, peak] — for tests
) -> RequestResult:
    async with semaphore:
        in_flight_counter[0] += 1
        if in_flight_counter[0] > in_flight_counter[1]:
            in_flight_counter[1] = in_flight_counter[0]
        t0 = time.perf_counter()
        try:
            async with session.request(
                method,
                url,
                data=body,
                timeout=timeout,
            ) as resp:
                await resp.read()  # include body download in the timing window
                latency_ms = (time.perf_counter() - t0) * 1000
                success = 200 <= resp.status < 300
                return RequestResult(
                    latency_ms=latency_ms,
                    status_code=resp.status,
                    success=success,
                    error_type=None if success else "non_2xx",
                )
        except asyncio.TimeoutError:
            latency_ms = (time.perf_counter() - t0) * 1000
            return RequestResult(
                latency_ms=latency_ms,
                status_code=None,
                success=False,
                error_type="timeout",
            )
        except aiohttp.ClientConnectionError:
            latency_ms = (time.perf_counter() - t0) * 1000
            return RequestResult(
                latency_ms=latency_ms,
                status_code=None,
                success=False,
                error_type="connection_error",
            )
        except Exception:
            latency_ms = (time.perf_counter() - t0) * 1000
            return RequestResult(
                latency_ms=latency_ms,
                status_code=None,
                success=False,
                error_type="error",
            )
        finally:
            in_flight_counter[0] -= 1


async def run(
    url: str,
    n_requests: int,
    concurrency: int,
    method: str = "GET",
    timeout_s: float = 30.0,
    headers: dict[str, str] | None = None,
    body: str | None = None,
) -> tuple[list[RequestResult], float, list[int]]:
    """
    Fire n_requests HTTP calls bounded by concurrency.

    Returns (results, wall_clock_seconds, in_flight_tracker) where
    in_flight_tracker is [current, peak] — exposed for testing.
    """
    semaphore = asyncio.Semaphore(concurrency)
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    connector = aiohttp.TCPConnector(limit=concurrency)
    in_flight: list[int] = [0, 0]  # [current, peak]

    async with aiohttp.ClientSession(
        connector=connector,
        headers=headers or {},
    ) as session:
        wall_start = time.perf_counter()
        tasks = [
            asyncio.create_task(
                _single_request(session, semaphore, method, url, timeout, body, in_flight)
            )
            for _ in range(n_requests)
        ]
        results: list[RequestResult] = await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - wall_start

    return list(results), wall_elapsed, in_flight
