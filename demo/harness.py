"""Bring up the services S1 needs, run it, tear them down.

Separate from run.py so the presentation logic contains no process management
and the process management contains no formatting -- the demo script should be
readable on a projector.
"""

from __future__ import annotations

import os
import pathlib
import signal
import socket
import subprocess
import sys
import time

import httpx

REPO = pathlib.Path(__file__).resolve().parents[1]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spawn(module: str, port: int, env_extra: dict, workers: int = 4) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(REPO), **env_extra}
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1",
         "--port", str(port), "--workers", str(workers), "--log-level", "error"],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _wait_plain(url: str) -> None:
    """No actor headers -- the coordinator is not behind the actor middleware."""
    for _ in range(120):
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"coordinator never became healthy: {url}")


def _wait(url: str) -> None:
    probe = {"X-Actor-Id": "DEMO", "X-Schedule-Id": "DEMO"}
    for _ in range(120):
        try:
            if httpx.get(url, timeout=2.0, headers=probe).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"service never became healthy: {url}")


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

    coord_port = _free_port()
    # ONE worker, always. The coordinator holds the schedule pointer and its
    # parked waiters in process memory, so a second worker holds a different
    # one: the declare lands on one and the awaits on another, which surfaces
    # as "no schedule declared" from a coordinator that is running fine.
    coord = _spawn("apps.coordinator.main:app", coord_port, {}, workers=1)
    coord_url = f"http://127.0.0.1:{coord_port}"

    # Everything spawned goes in `procs` BEFORE anything can raise. The first
    # version spawned the coordinator outside the try, so a service that never
    # became healthy left it running forever -- three accumulated during
    # development and tripped the orphan guard, erroring 65 unrelated tests.
    procs = [coord]
    try:
        # /waiters, not /health -- the coordinator has no health route. Waiting
        # on a 404 forever is how this first failed.
        _wait_plain(f"{coord_url}/waiters")

        env = {"BARRIER_ENABLED": "1", "BARRIER_URL": coord_url,
               "ACL_ENFORCE_POLICY": "1"}
        ports = {name: _free_port() for name in ("billing", "ledger", "crm")}
        for name, port in ports.items():
            procs.append(_spawn(f"apps.{name}.main:app", port, env))
        for name, port in ports.items():
            _wait(f"http://127.0.0.1:{port}/health")

        stack = {"coordinator": coord_url,
                 **{n: f"http://127.0.0.1:{p}" for n, p in ports.items()}}
        return run_schedule("S1", stack)
    finally:
        for proc in procs:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
