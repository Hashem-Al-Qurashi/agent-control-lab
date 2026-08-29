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
from apps.control.db import run_migrations as control_migrations
from apps.control.db import truncate_all as control_truncate
from apps.crm.db import run_migrations as crm_migrations
from apps.crm.db import truncate_all as crm_truncate
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


def _assert_no_orphaned_services() -> None:
    """Fail loudly if services from a previous run are still alive.

    A killed or crashed suite can leave uvicorn workers holding connections to
    the same databases. They do not act on their own, but they compete for
    connections and CPU, and timing-sensitive behaviour then diverges.

    This was observed once: a full-suite run reported P0 and P2 replays
    diverging, and did not reproduce in three subsequent runs after orphaned
    processes were cleared. That is a determinism claim quietly depending on a
    clean machine -- so the dependency is now checked rather than assumed.

    Failing here is correct. A polluted environment silently produces
    unreproducible results, which is the exact failure this harness exists to
    make impossible.
    """
    result = subprocess.run(
        ["pgrep", "-f", "uvicorn apps\\."], capture_output=True, text=True
    )
    pids = [p for p in result.stdout.split() if p]
    if pids:
        raise RuntimeError(
            f"{len(pids)} orphaned service process(es) from a previous run are "
            f"still alive (pids {pids}). They compete for the same databases and "
            "make timing-sensitive results unreproducible. Clear them with:\n"
            "    pkill -f 'uvicorn apps\\.'"
        )


@pytest.fixture(scope="session")
def stack():
    _assert_no_orphaned_services()
    billing_migrations()
    ledger_migrations()
    control_migrations()
    crm_migrations()
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

    # Enforcement ON for schedules. Otherwise "the failure occurred despite
    # proper authorization" would rest on unit tests rather than on the runs.
    service_env = {
        "BARRIER_ENABLED": "1",
        "BARRIER_URL": coord_url,
        "ACL_ENFORCE_POLICY": "1",
    }
    billing_port, ledger_port = _free_port(), _free_port()
    billing = _spawn("apps.billing.main:app", billing_port, service_env, workers=4)
    ledger = _spawn("apps.ledger.main:app", ledger_port, service_env, workers=4)
    # The control service takes no part in any schedule, so it runs without
    # barrier participation. It is the fix under test, not a racing actor.
    control_port = _free_port()
    control = _spawn(
        "apps.control.main:app", control_port, {"BARRIER_ENABLED": "0"}, workers=4
    )
    # CRM participates in schedules -- its projector holds a checkpoint -- so it
    # runs with the barrier enabled, unlike the control service.
    crm_port = _free_port()
    crm = _spawn("apps.crm.main:app", crm_port, service_env, workers=4)

    probe = {"X-Actor-Id": "PROBE", "X-Schedule-Id": "PROBE"}
    _wait_for(f"http://127.0.0.1:{billing_port}/health", probe)
    _wait_for(f"http://127.0.0.1:{ledger_port}/health", probe)
    _wait_for(f"http://127.0.0.1:{control_port}/health", probe)
    _wait_for(f"http://127.0.0.1:{crm_port}/health", probe)

    yield {
        "coordinator": coord_url,
        "billing": f"http://127.0.0.1:{billing_port}",
        "ledger": f"http://127.0.0.1:{ledger_port}",
        "control": f"http://127.0.0.1:{control_port}",
        "crm": f"http://127.0.0.1:{crm_port}",
    }

    for proc in (billing, ledger, control, crm, coord):
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
    control_truncate()
    crm_truncate()
    yield stack
    httpx.post(f"{stack['coordinator']}/reset", timeout=10.0)
