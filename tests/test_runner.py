"""Integration tests for the async runner engine.

The test server is a real aiohttp Application started in-process via
aiohttp's pytest plugin (pytest-aiohttp is not a dependency, so we spin
it up manually using aiohttp.web.AppRunner on a random port). This keeps
the test hermetic with no external network calls.
"""
from __future__ import annotations

import asyncio
import time

import aiohttp.web
import pytest

from loadtest.runner import run


# ---------------------------------------------------------------------------
# Minimal local test server
# ---------------------------------------------------------------------------

async def _handle_ok(request: aiohttp.web.Request) -> aiohttp.web.Response:
    return aiohttp.web.Response(text="ok")


async def _handle_slow(request: aiohttp.web.Request) -> aiohttp.web.Response:
    await asyncio.sleep(0.3)
    return aiohttp.web.Response(text="slow")


async def _handle_error(request: aiohttp.web.Request) -> aiohttp.web.Response:
    return aiohttp.web.Response(status=500, text="boom")


@pytest.fixture
async def local_server():
    """Spin up a real aiohttp server on a random port; yield its base URL."""
    app = aiohttp.web.Application()
    app.router.add_get("/ok", _handle_ok)
    app.router.add_get("/slow", _handle_slow)
    app.router.add_get("/error", _handle_error)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    # Retrieve the actual bound port
    sockets = site._server.sockets  # type: ignore[attr-defined]
    port = sockets[0].getsockname()[1]

    yield f"http://127.0.0.1:{port}"

    await runner.cleanup()


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------

class TestRunnerBasic:
    async def test_all_succeed(self, local_server: str):
        results, elapsed, _ = await run(
            url=f"{local_server}/ok",
            n_requests=20,
            concurrency=5,
        )
        assert len(results) == 20
        assert all(r.success for r in results)
        assert all(r.status_code == 200 for r in results)
        assert all(r.error_type is None for r in results)

    async def test_non_2xx_counted_as_failure(self, local_server: str):
        results, _, _ = await run(
            url=f"{local_server}/error",
            n_requests=10,
            concurrency=5,
        )
        assert len(results) == 10
        assert all(not r.success for r in results)
        assert all(r.error_type == "non_2xx" for r in results)
        assert all(r.status_code == 500 for r in results)

    async def test_timeout_failure_does_not_crash_run(self, local_server: str):
        # /slow sleeps 0.3 s; we set timeout to 0.05 s → all time out
        results, _, _ = await run(
            url=f"{local_server}/slow",
            n_requests=5,
            concurrency=5,
            timeout_s=0.05,
        )
        assert len(results) == 5
        # All should be recorded as failures; the run must complete
        failed = [r for r in results if not r.success]
        assert len(failed) == 5
        assert all(r.error_type == "timeout" for r in failed)

    async def test_mixed_endpoints_counts(self, local_server: str):
        # Run against /ok — verify counts line up
        results, elapsed, _ = await run(
            url=f"{local_server}/ok",
            n_requests=30,
            concurrency=10,
        )
        succeeded = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        assert succeeded + failed == 30
        assert succeeded == 30

    async def test_latency_recorded_for_all_requests(self, local_server: str):
        results, _, _ = await run(
            url=f"{local_server}/ok",
            n_requests=10,
            concurrency=5,
        )
        assert all(r.latency_ms > 0 for r in results)


# ---------------------------------------------------------------------------
# Semaphore / concurrency bound
# ---------------------------------------------------------------------------

class TestConcurrencyBound:
    async def test_in_flight_never_exceeds_limit(self, local_server: str):
        """
        The runner tracks [current_in_flight, peak_in_flight].
        We use a slow endpoint so requests overlap and the semaphore is
        exercised. Peak must not exceed concurrency.
        """
        concurrency = 4
        # /slow takes 0.3 s; with concurrency=4 and 12 requests they will
        # definitely overlap — peak should be exactly concurrency.
        results, _, in_flight = await run(
            url=f"{local_server}/slow",
            n_requests=12,
            concurrency=concurrency,
        )
        peak = in_flight[1]
        assert peak <= concurrency, f"Peak in-flight {peak} exceeded concurrency {concurrency}"

    async def test_concurrency_1_serialises_requests(self, local_server: str):
        """With concurrency=1 requests are strictly serialised."""
        results, elapsed, in_flight = await run(
            url=f"{local_server}/ok",
            n_requests=5,
            concurrency=1,
        )
        assert in_flight[1] == 1
        assert len(results) == 5

    async def test_semaphore_bounds_with_fast_endpoint(self, local_server: str):
        concurrency = 3
        results, _, in_flight = await run(
            url=f"{local_server}/ok",
            n_requests=50,
            concurrency=concurrency,
        )
        assert in_flight[1] <= concurrency
        assert len(results) == 50
