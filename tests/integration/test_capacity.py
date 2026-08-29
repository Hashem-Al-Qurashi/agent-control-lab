"""Stage 5: does the coordination authority hold under real concurrency?

Every other test in this repo drives a scripted interleaving. That is deliberate
-- determinism is what makes a violation attributable. But it leaves one question
open: the schedules exercise two or three actors in an order we chose. Does the
reservation authority actually hold the ceiling when many agents contend for it
at once, in an order nobody chose?

This is the complement to the deterministic suite, not a replacement. It cannot
say WHY anything happened. It can say whether the invariant survived.

The correctness assertion matters more than the latency numbers. A control that
is fast and occasionally wrong is worse than one that is slow and always right,
because the wrongness is what nobody notices.
"""

import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import psycopg2
import pytest

from apps.control.db import run_migrations, truncate_all

CONTROL_DSN = "postgresql://control:control@127.0.0.1:55435/control"
CEILING = Decimal("1000.00")
GRANT = Decimal("100.00")  # ceiling admits exactly 10


@pytest.fixture(scope="module")
def control_url():
    import os
    import pathlib
    import signal
    import socket
    import subprocess
    import sys

    repo = pathlib.Path(__file__).resolve().parents[2]
    run_migrations()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "apps.control.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--workers", "4",
         "--log-level", "error"],
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(repo), "BARRIER_ENABLED": "0"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    headers = {"X-Actor-Id": "CAP", "X-Schedule-Id": "CAP"}
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{url}/health", headers=headers, timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:  # pragma: no cover
        proc.send_signal(signal.SIGTERM)
        pytest.fail("control did not start")

    yield url
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=15)


def _granted_total(case_id: str) -> Decimal:
    conn = psycopg2.connect(CONTROL_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM reservations "
                "WHERE case_id = %s AND state IN ('HELD', 'COMMITTED')",
                (case_id,),
            )
            return Decimal(cur.fetchone()[0])
    finally:
        conn.close()


def _contend(url, case_id, n):
    """n agents race for a ceiling that admits only 10. Returns (granted, latencies)."""
    def attempt(i):
        t0 = time.monotonic()
        r = httpx.post(
            f"{url}/reservations",
            json={"case_id": case_id, "amount": str(GRANT),
                  "idempotency_key": f"{case_id}-{i}",
                  "authorized_compensation": str(CEILING)},
            headers={"X-Actor-Id": f"A{i}", "X-Schedule-Id": "CAP"},
            timeout=60.0,
        )
        return r.status_code, time.monotonic() - t0

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(attempt, range(n)))

    granted = sum(1 for code, _ in results if code == 201)
    return granted, [d for _, d in results]


@pytest.mark.parametrize("concurrency", [10, 50, 100])
def test_the_ceiling_holds_under_contention(control_url, concurrency):
    """The load-bearing assertion.

    Every agent's request is individually valid. Only ten can be granted. If the
    authority admits an eleventh, the primitive that P0 and S1H rely on does not
    actually hold, and both of those results are worthless.
    """
    truncate_all()
    case_id = f"cap-{concurrency}"

    granted, latencies = _contend(control_url, case_id, concurrency)

    total = _granted_total(case_id)
    assert total <= CEILING, (
        f"{concurrency} concurrent agents drove the total to {total}, above the "
        f"{CEILING} ceiling -- the advisory lock does not serialise correctly and "
        "every reservation-based result in this repo is invalid"
    )
    assert granted == 10, f"expected exactly 10 grants, got {granted}"
    assert total == Decimal("1000.00")

    ordered = sorted(latencies)
    print(
        f"\n  concurrency={concurrency:>3}  granted={granted:>3}  "
        f"total={total}  "
        f"p50={statistics.median(ordered)*1000:6.1f}ms  "
        f"p95={ordered[int(len(ordered)*0.95)-1]*1000:6.1f}ms  "
        f"p99={ordered[int(len(ordered)*0.99)-1]*1000:6.1f}ms  "
        f"max={ordered[-1]*1000:6.1f}ms"
    )


def test_refusals_are_refusals_not_errors(control_url):
    """Under contention the losers must get a clean 409, not a 500.

    A refusal that surfaces as a server error is indistinguishable from an
    outage, and an agent cannot tell 'you may not' from 'try again later'.
    """
    truncate_all()

    def attempt(i):
        return httpx.post(
            f"{control_url}/reservations",
            json={"case_id": "cap-errors", "amount": str(GRANT),
                  "idempotency_key": f"err-{i}",
                  "authorized_compensation": str(CEILING)},
            headers={"X-Actor-Id": f"A{i}", "X-Schedule-Id": "CAP"},
            timeout=60.0,
        ).status_code

    with ThreadPoolExecutor(max_workers=50) as pool:
        codes = list(pool.map(attempt, range(50)))

    assert set(codes) <= {201, 409}, f"unexpected status codes: {sorted(set(codes))}"
    assert codes.count(201) == 10
