"""Full-stack fixture: coordinator plus both services, all as real servers.

Services run multi-worker on real sockets. An in-process test client would
serialise the two actors and every schedule would pass for the wrong reason --
the exact silent failure Task 13 exists to detect.

Calibration runs once before any schedule. An oracle that has not demonstrably
caught a planted violation and passed a planted safe state is unproven
instrumentation, and every verdict below would inherit that doubt.
"""

import os
import pathlib
import signal
import socket
import subprocess
import sys
import time

import httpx
import pytest

from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from apps.ledger.db import run_migrations as ledger_migrations
from apps.ledger.db import truncate_all as ledger_truncate
from oracle.calibration import calibrate
from oracle.quiescence import grant_readonly

REPO = pathlib.Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for(url: str, headers=None, timeout=45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.get(url, headers=headers or {}, timeout=0.5)
            return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError(f"{url} did not become ready")


def _spawn(module: str, port: int, env_extra: dict, workers: int) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(REPO), **env_extra}
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", module,
            "--host", "127.0.0.1", "--port", str(port),
            "--workers", str(workers), "--log-level", "error",
        ],
        cwd=REPO, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@pytest.fixture(scope="session")
def stack():
    billing_migrations()
    ledger_migrations()
    grant_readonly()

    # The oracle proves itself before it is allowed to judge anything.
    calibrate()

    coord_port = _free_port()
    # Coordinator is deliberately single-worker: it holds the schedule pointer
    # and parked waiters in process memory, so a second worker would hold a
    # second, divergent barrier.
    coord = _spawn("apps.coordinator.main:app", coord_port, {}, workers=1)
    coord_url = f"http://127.0.0.1:{coord_port}"
    _wait_for(f"{coord_url}/waiters")

    service_env = {"BARRIER_ENABLED": "1", "BARRIER_URL": coord_url}
    billing_port, ledger_port = _free_port(), _free_port()
    billing = _spawn("apps.billing.main:app", billing_port, service_env, workers=4)
    ledger = _spawn("apps.ledger.main:app", ledger_port, service_env, workers=4)

    probe = {"X-Actor-Id": "PROBE", "X-Schedule-Id": "PROBE"}
    _wait_for(f"http://127.0.0.1:{billing_port}/health", probe)
    _wait_for(f"http://127.0.0.1:{ledger_port}/health", probe)

    yield {
        "coordinator": coord_url,
        "billing": f"http://127.0.0.1:{billing_port}",
        "ledger": f"http://127.0.0.1:{ledger_port}",
    }

    for proc in (billing, ledger, coord):
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()


@pytest.fixture()
def clean_state(stack):
    """Verified clean slate. Leftover rows push a sum over the ceiling
    regardless of concurrency, which is indistinguishable from a real
    violation."""
    httpx.post(f"{stack['coordinator']}/reset", timeout=10.0)
    billing_truncate()
    ledger_truncate()
    yield stack
    httpx.post(f"{stack['coordinator']}/reset", timeout=10.0)
