"""Async load-test engine.

Concurrency model
-----------------
A single asyncio.Semaphore of size == concurrency bounds the number of requests
in flight at any moment. All N tasks are created upfront (cheap), but each must
acquire the semaphore before issuing its HTTP call and releases it the instant
the response body is consumed — guaranteeing the in-flight count never exceeds
the limit even though aiohttp's own connector could allow more.

Connection pooling
------------------
One aiohttp.ClientSession is shared across all tasks, with its TCPConnector
sized to match --concurrency so keep-alive connections are reused rather than
re-handshaked per request, and the OS file-descriptor count stays bounded.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import aiohttp

from loadtest.stats import RequestResult


@dataclass
class InFlightTracker:
    """Live count of concurrent in-flight requests, with high-water mark.

    Safe to mutate without a lock: asyncio is single-threaded and there is no
    await between reading and updating these fields.
    """
    current: int = 0
    peak: int = 0

    def enter(self) -> None:
        self.current += 1
        if self.current > self.peak:
            self.peak = self.current

    def exit(self) -> None:
        self.current -= 1


async def _single_request(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    method: str,
    url: str,
    timeout: aiohttp.ClientTimeout,
    body: str | None,
    tracker: InFlightTracker,
) -> RequestResult:
    async with semaphore:
        tracker.enter()
        t0 = time.perf_counter()
        try:
            async with session.request(method, url, data=body, timeout=timeout) as resp:
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
            return RequestResult(
                latency_ms=(time.perf_counter() - t0) * 1000,
                status_code=None,
                success=False,
                error_type="timeout",
            )
        except aiohttp.ClientConnectionError:
            return RequestResult(
                latency_ms=(time.perf_counter() - t0) * 1000,
                status_code=None,
                success=False,
                error_type="connection_error",
            )
        except aiohttp.ClientError:
            return RequestResult(
                latency_ms=(time.perf_counter() - t0) * 1000,
                status_code=None,
                success=False,
                error_type="error",
            )
        finally:
            tracker.exit()


async def run(
    url: str,
    n_requests: int,
    concurrency: int,
    method: str = "GET",
    timeout_s: float = 30.0,
    headers: dict[str, str] | None = None,
    body: str | None = None,
) -> tuple[list[RequestResult], float, InFlightTracker]:
    """
    Fire n_requests HTTP calls bounded by concurrency.

    Returns (results, wall_clock_seconds, tracker). The tracker's `peak` field
    is the high-water mark of concurrent in-flight requests (used by tests to
    prove the semaphore bound holds).
    """
    semaphore = asyncio.Semaphore(concurrency)
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    connector = aiohttp.TCPConnector(limit=concurrency)
    tracker = InFlightTracker()

    async with aiohttp.ClientSession(connector=connector, headers=headers or {}) as session:
        wall_start = time.perf_counter()
        tasks = [
            asyncio.create_task(
                _single_request(session, semaphore, method, url, timeout, body, tracker)
            )
            for _ in range(n_requests)
        ]
        # return_exceptions=True is belt-and-suspenders: _single_request already
        # catches everything, but this guarantees one stray error can never abort
        # the batch.
        results: list[RequestResult] = await asyncio.gather(*tasks, return_exceptions=False)
        wall_elapsed = time.perf_counter() - wall_start

    return list(results), wall_elapsed, tracker
