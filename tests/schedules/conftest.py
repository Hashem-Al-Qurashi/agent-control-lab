"""Full-stack fixture: coordinator plus both services, all as real servers.

Services run multi-worker on real sockets. An in-process test client would
serialise the two actors and every schedule would pass for the wrong reason --
the exact silent failure Task 13 exists to detect.

Calibration runs once before any schedule. An oracle that has not demonstrably
caught a planted violation and passed a planted safe state is unproven
instrumentation, and every verdict below would inherit that doubt.
"""

import pathlib
import signal
import socket
import time

import httpx
import pytest

from libs.servicelab import spawn_service, stop_all
from libs.procguard import (
    ProcessOwnership,
    parent_map,
    running_service_pids,
)

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


OWNERSHIP = ProcessOwnership()


def _spawn(module, port, env_extra, workers=4):
    """Thin wrapper over the shared spawner, adding ownership tracking.

    The lifecycle itself lives in libs/servicelab.py because demo/harness.py
    needs the same thing, and the copy it once had reintroduced two bugs this
    file had already solved.
    """
    return spawn_service(module, port, env_extra, workers, on_spawn=OWNERSHIP.claim)


def _stop(procs) -> None:
    """Terminate services and stop vouching for their pids."""
    stop_all(procs, on_stop=OWNERSHIP.release)


def _assert_no_orphaned_services() -> None:
    """Fail loudly if services from a *previous* run are still alive.

    A killed or crashed suite can leave uvicorn workers holding connections to
    the same databases. They do not act on their own, but they compete for
    connections and CPU, and timing-sensitive behaviour then diverges.

    This was observed once: a full-suite run reported P0 and P2 replays
    diverging, and did not reproduce in three subsequent runs after orphaned
    processes were cleared. That is a determinism claim quietly depending on a
    clean machine -- so the dependency is checked rather than assumed.

    The check must exclude processes this session started, or it measures the
    suite instead of the environment. It did exactly that: `stack` and
    `natural_stack` are both session-scoped and both spawn services, so the
    second one built saw the first one's live processes and aborted, erroring 53
    tests that every one of them passed in isolation.
    """
    foreign = OWNERSHIP.foreign(running_service_pids(), parent_map())
    if foreign:
        raise RuntimeError(
            f"{len(foreign)} orphaned service process(es) from a previous run "
            f"are still alive (pids {foreign}). They compete for the same "
            "databases and make timing-sensitive results unreproducible. "
            "Clear them with:\n    pkill -f 'uvicorn apps\\.'"
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

    _stop((billing, ledger, control, crm, coord))


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


@pytest.fixture(scope="module")
def llm_stack():
    """Billing, ledger and the control service, barrier disabled.

    Separate from natural_stack because arms C and D need the coordination
    authority, and module-scoped for the reason ADR-007 records: a session-scoped
    stack stays alive on the same databases through every schedule that follows.
    """
    _assert_no_orphaned_services()
    billing_migrations()
    ledger_migrations()
    control_migrations()
    grant_readonly()

    env = {"BARRIER_ENABLED": "0", "ACL_ENFORCE_POLICY": "0"}
    billing_port, ledger_port, control_port = _free_port(), _free_port(), _free_port()
    procs = [
        _spawn("apps.billing.main:app", billing_port, env, workers=4),
        _spawn("apps.ledger.main:app", ledger_port, env, workers=4),
        _spawn("apps.control.main:app", control_port, env, workers=4),
    ]
    probe = {"X-Actor-Id": "PROBE", "X-Schedule-Id": "PROBE"}
    try:
        for port in (billing_port, ledger_port, control_port):
            _wait_for(f"http://127.0.0.1:{port}/health", probe)
    except RuntimeError:  # pragma: no cover
        _stop(procs)
        raise

    yield {
        "billing": f"http://127.0.0.1:{billing_port}",
        "ledger": f"http://127.0.0.1:{ledger_port}",
        "control": f"http://127.0.0.1:{control_port}",
    }
    _stop(procs)


@pytest.fixture(scope="module")
def natural_stack():
    """Mode B stack: services with the barrier disabled.

    Module-scoped, not session-scoped, and the distinction is load-bearing.
    Only test_mode_b.py uses this, and it collects FIRST -- so at session scope
    these two multi-worker services stayed alive on the *same* billing and
    ledger databases through every schedule that followed, starting with P0 and
    P2. Those are exactly the two schedules ADR-007 recorded as diverging.

    That makes overlap a candidate cause for the anomaly, and it also means the
    orphan guard alone was not a fix: teaching it to recognise these processes
    as ours stopped the false alarm without removing the contention. Module
    scope removes it -- same reuse inside the one module that needs it, released
    before anything else runs.

    A separate stack rather than reusing Mode A's. The barrier fails closed when
    no schedule is declared -- correctly -- so Mode A's services cannot serve
    unscheduled traffic. Adding a permissive "release everything" schedule would
    contradict the fail-closed design every Mode A result depends on.
    """
    _assert_no_orphaned_services()
    billing_migrations()
    ledger_migrations()
    grant_readonly()

    env = {"BARRIER_ENABLED": "0", "ACL_ENFORCE_POLICY": "0"}
    billing_port, ledger_port = _free_port(), _free_port()
    procs = [
        _spawn("apps.billing.main:app", billing_port, env, workers=4),
        _spawn("apps.ledger.main:app", ledger_port, env, workers=4),
    ]

    probe = {"X-Actor-Id": "PROBE", "X-Schedule-Id": "PROBE"}
    try:
        for port in (billing_port, ledger_port):
            _wait_for(f"http://127.0.0.1:{port}/health", probe)
    except RuntimeError:  # pragma: no cover
        for p in procs:
            p.send_signal(signal.SIGTERM)
        raise

    yield {
        "billing": f"http://127.0.0.1:{billing_port}",
        "ledger": f"http://127.0.0.1:{ledger_port}",
    }

    _stop(procs)
