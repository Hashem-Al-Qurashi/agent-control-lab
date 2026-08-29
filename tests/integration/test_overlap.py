"""Task 13: prove the two actors are genuinely concurrent at the server.

This guards the quietest failure in the whole rig. If requests serialise --
single worker, a connection pool of one, an accidental lock -- then P2 executes
as P1, produces no violation, and the honest-looking conclusion is that the
thesis is false. The rig would have disproved something it never tested.

Client-side overlap is necessary but not sufficient: two clients can believe
they overlapped while the server handled them back to back. So overlap is
asserted on BOTH sides, and the server-side record is the authority.
"""

import os
import pathlib
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from apps.billing.db import connect, run_migrations, truncate_all

REPO = pathlib.Path(__file__).resolve().parents[2]
HEADERS = {"X-Actor-Id": "A", "X-Schedule-Id": "P1"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def billing_server():
    run_migrations()
    port = _free_port()
    env = {**os.environ, "BARRIER_ENABLED": "0", "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "apps.billing.main:app",
            "--host", "127.0.0.1", "--port", str(port),
            "--workers", "4", "--log-level", "error",
        ],
        cwd=REPO, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 40.0
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{url}/health", headers=HEADERS, timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:  # pragma: no cover
        proc.send_signal(signal.SIGTERM)
        pytest.fail("billing did not start")

    yield url
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=15)


def _server_side_intervals():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT actor_id, started_at, ended_at FROM request_log "
            "WHERE ended_at IS NOT NULL ORDER BY started_at"
        )
        return cur.fetchall()


def _any_pair_overlaps(intervals) -> bool:
    for i, (_, s1, e1) in enumerate(intervals):
        for _, s2, e2 in intervals[i + 1 :]:
            if s2 < e1 and s1 < e2:
                return True
    return False


def test_requests_overlap_on_both_client_and_server(billing_server):
    truncate_all()

    def hit(n):
        t0 = time.monotonic()
        httpx.get(
            f"{billing_server}/refunds",
            params={"case_id": f"case-{n}"},
            headers={"X-Actor-Id": "A" if n % 2 else "B", "X-Schedule-Id": "P1"},
            timeout=30.0,
        )
        return t0, time.monotonic()

    with ThreadPoolExecutor(max_workers=16) as pool:
        client_intervals = list(pool.map(hit, range(24)))

    assert _any_pair_overlaps(
        [("client", s, e) for s, e in client_intervals]
    ), "no two requests overlapped client-side"

    server_intervals = _server_side_intervals()
    assert len(server_intervals) >= 24, (
        f"server recorded {len(server_intervals)} requests, expected >= 24"
    )
    assert _any_pair_overlaps(server_intervals), (
        "the server handled every request back to back -- requests are "
        "serialising, so P2 would execute as P1 and read as the thesis being "
        "false"
    )


def test_both_actors_are_recorded_server_side(billing_server):
    """Identity must survive to the server, or overlap proves nothing about actors."""
    truncate_all()

    def hit(actor):
        httpx.get(
            f"{billing_server}/refunds",
            params={"case_id": "case-1"},
            headers={"X-Actor-Id": actor, "X-Schedule-Id": "P1"},
            timeout=30.0,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(hit, ["A", "B", "A", "B"]))

    actors = {row[0] for row in _server_side_intervals()}
    assert actors == {"A", "B"}, f"server saw actors {actors}"
