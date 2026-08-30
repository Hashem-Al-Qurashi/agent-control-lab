"""Spawning and stopping the lab's services, in one place.

Extracted after demo/harness.py reimplemented this and reintroduced two bugs the
original had already solved: it spawned the coordinator with four workers (which
holds its schedule pointer in process memory, so the declare and the awaits land
on different workers), and it waited on /health, which the coordinator does not
have.

Both were solved in tests/schedules/conftest.py before the demo was written. The
duplication is what let them come back, so there is now one implementation and
the knowledge lives with it.
"""

from __future__ import annotations

import os
import pathlib
import signal
import socket
import subprocess
import sys
from typing import Callable

import httpx

REPO = pathlib.Path(__file__).resolve().parents[1]

# The coordinator holds the schedule pointer and its parked waiters in process
# memory. A second worker holds a different one.
COORDINATOR_WORKERS = 1
# The coordinator has no /health route; readiness is /waiters.
COORDINATOR_READY_PATH = "/waiters"


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def spawn_service(
    module: str,
    port: int,
    env_extra: dict | None = None,
    workers: int = 4,
    on_spawn: Callable[[int], None] | None = None,
) -> subprocess.Popen:
    """Start one uvicorn service. `on_spawn` receives the pid, for ownership."""
    env = {**os.environ, "PYTHONPATH": str(REPO), **(env_extra or {})}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", module,
            "--host", "127.0.0.1", "--port", str(port),
            "--workers", str(workers), "--log-level", "error",
        ],
        cwd=REPO, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if on_spawn is not None:
        on_spawn(proc.pid)
    return proc


def spawn_coordinator(port: int, on_spawn=None) -> subprocess.Popen:
    """The coordinator, with the worker count that is not negotiable."""
    return spawn_service(
        "apps.coordinator.main:app", port, {},
        workers=COORDINATOR_WORKERS, on_spawn=on_spawn,
    )


def wait_for(url: str, headers: dict | None = None, attempts: int = 120) -> None:
    import time

    for _ in range(attempts):
        try:
            if httpx.get(url, timeout=2.0, headers=headers or {}).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"never became ready: {url}")


def stop_all(procs, on_stop: Callable[[int], None] | None = None) -> None:
    """Terminate every process, killing any that will not go."""
    for proc in procs:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
        if on_stop is not None:
            on_stop(proc.pid)
