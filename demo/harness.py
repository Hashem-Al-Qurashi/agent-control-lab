"""Bring up the services S1 needs, run it, tear them down.

Process management lives in libs/servicelab.py, shared with the test fixtures.
Writing a second copy here is what produced this file's original two bugs.
"""

from __future__ import annotations

from libs.servicelab import (
    COORDINATOR_READY_PATH,
    free_port,
    spawn_coordinator,
    spawn_service,
    stop_all,
    wait_for,
)


def run_s1():
    from apps.billing.db import run_migrations as bm
    from apps.billing.db import truncate_all as bt
    from apps.crm.db import run_migrations as cm
    from apps.crm.db import truncate_all as ct
    from apps.ledger.db import run_migrations as lm
    from apps.ledger.db import truncate_all as lt
    from oracle.quiescence import grant_readonly
    from schedules.runner import run_schedule

    bm(); lm(); cm(); grant_readonly()
    bt(); lt(); ct()

    coord_port = free_port()
    coord_url = f"http://127.0.0.1:{coord_port}"

    # Everything spawned enters `procs` BEFORE anything can raise. The first
    # version spawned the coordinator outside the try, so a service that never
    # became healthy left it running forever -- three accumulated during
    # development and tripped the orphan guard, erroring 65 unrelated tests.
    procs = [spawn_coordinator(coord_port)]
    try:
        wait_for(coord_url + COORDINATOR_READY_PATH)

        env = {"BARRIER_ENABLED": "1", "BARRIER_URL": coord_url,
               "ACL_ENFORCE_POLICY": "1"}
        ports = {name: free_port() for name in ("billing", "ledger", "crm")}
        for name, port in ports.items():
            procs.append(spawn_service(f"apps.{name}.main:app", port, env))

        probe = {"X-Actor-Id": "DEMO", "X-Schedule-Id": "DEMO"}
        for port in ports.values():
            wait_for(f"http://127.0.0.1:{port}/health", probe)

        stack = {"coordinator": coord_url,
                 **{n: f"http://127.0.0.1:{p}" for n, p in ports.items()}}
        return run_schedule("S1", stack)
    finally:
        stop_all(procs)
