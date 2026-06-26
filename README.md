# loadtest

An async HTTP load-testing CLI tool. Fires a configurable volume of concurrent
requests at a target URL and reports latency percentiles, throughput, and error
rates with accurate measurements.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # includes pytest + pytest-asyncio
```

Requires Python 3.11+.

## Usage

```
loadtest <url> [options]

Options:
  -n, --requests N     Total number of requests (default: 100)
  -c, --concurrency C  Max in-flight requests at once (default: 10)
  -m, --method METHOD  HTTP method (default: GET)
  -t, --timeout SECS   Per-request timeout in seconds (default: 30)
  -H KEY:VALUE         Request header, repeatable
  --body TEXT          Request body string
  --json               Output results as JSON
```

### Examples

```bash
# 200 GET requests, 20 concurrent
loadtest https://httpbin.org/get -n 200 -c 20

# POST with headers and body
loadtest https://httpbin.org/post -m POST \
  -H "Content-Type: application/json" \
  --body '{"key": "value"}' \
  -n 50 -c 5

# Machine-readable JSON output
loadtest https://httpbin.org/get -n 100 -c 10 --json
```

### Sample output

```
==================================================
  Load Test Results
==================================================
  Total requests:       100
  Succeeded:            100
  Failed:               0
  Throughput:           47.83 req/s

  Latency (ms):
    min:                89.42
    mean:               196.31
    p50:                182.14
    p90:                312.87
    p95:                381.55
    p99:                512.03
    max:                601.22
==================================================
```

### JSON output

```json
{
  "total": 100,
  "succeeded": 100,
  "failed": 0,
  "throughput_rps": 47.83,
  "latency_ms": {
    "min": 89.42,
    "mean": 196.31,
    "p50": 182.14,
    "p90": 312.87,
    "p95": 381.55,
    "p99": 512.03,
    "max": 601.22
  },
  "error_breakdown": {}
}
```

## Tests

```bash
pytest -v
```

## Design notes

### Why semaphore-bounded concurrency

Spawning N tasks with `asyncio.gather` is tempting but incorrect for large N:
all tasks are scheduled immediately, so the event loop queues hundreds of
simultaneous `connect()` calls before the first response lands. The OS file-
descriptor limit and the server's accept queue both get hammered. The right
model is a bounded producer: create all tasks upfront (cheap), but each one
must acquire an `asyncio.Semaphore(concurrency)` before issuing any I/O and
release it the moment the response is consumed. This guarantees exactly C
requests are in flight at any instant, regardless of how fast individual
responses return.

### Why a single shared session

`aiohttp.ClientSession` manages a connection pool per host. Creating one session
per request defeats keep-alive: every request pays a fresh TCP handshake (and
TLS handshake for HTTPS), burning ~50–200 ms that would otherwise be zero. A
single session, with its `TCPConnector` sized to `--concurrency`, lets the pool
pre-warm during the first wave and reuse those connections for every subsequent
request — the same behaviour an HTTP/1.1-compliant client is supposed to exhibit.

### Why percentiles over means

The arithmetic mean is one number describing an entire distribution. For latency
that distribution is almost always right-skewed with a long tail: the slowest 1%
of requests can be 10–100× slower than the median, yet they barely move the
mean. A user hitting a p99 request experiences the *actual worst case* — SLOs,
timeout budgets, and retry strategies should all be calibrated to tail behaviour.
`p50` (median) tells you what a typical request feels like; `p90/p95/p99` tell
you how bad it gets for the unlucky minority. Optimising only the mean can leave
the tail completely unaddressed.
