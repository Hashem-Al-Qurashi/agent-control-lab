"""Pre-warmed pool of long-lived agent processes.

Agents run as separate OS processes, not threads. That is not incidental: with
threads, a shared HTTP session, a shared clock patch or a shared module global
can quietly serialise two actors that the schedule believes are independent, and
the run goes green having tested nothing.

Never fork-per-run. A Python process importing the agent stack costs seconds; at
the volumes later modes need that becomes hours of pure interpreter startup.
Pool size scales with concurrency, not with run count.

Workers pull from a dispatch queue and stay alive across cases, which is exactly
why agents/diligent/policy.py must pass the purity lint.
"""

from __future__ import annotations

import multiprocessing as mp
import os
from typing import Any

_SHUTDOWN = "__shutdown__"


def _worker(inbox: mp.Queue, outbox: mp.Queue) -> None:
    """Long-lived. One interpreter, many cases."""
    while True:
        job = inbox.get()
        if job == _SHUTDOWN:
            return
        kind, payload = job
        if kind == "echo_pid":
            outbox.put(os.getpid())
        elif kind == "run_case":
            # Imported inside the worker so configuration is never captured at
            # parent import time.
            from agents.diligent.policy import run_case

            case_id, config, clients = payload
            run_case(case_id, config, clients)
            outbox.put(("ok", case_id))
        else:  # pragma: no cover - defensive
            outbox.put(("error", f"unknown job {kind!r}"))


class AgentPool:
    def __init__(self, size: int = 2) -> None:
        ctx = mp.get_context("spawn")
        self._inbox: mp.Queue = ctx.Queue()
        self._outbox: mp.Queue = ctx.Queue()
        self._workers = [
            ctx.Process(target=_worker, args=(self._inbox, self._outbox), daemon=True)
            for _ in range(size)
        ]
        for w in self._workers:
            w.start()

    def submit_echo_pid(self, timeout: float = 30.0) -> int:
        """Diagnostic used to prove processes are reused rather than forked."""
        self._inbox.put(("echo_pid", None))
        return self._outbox.get(timeout=timeout)

    def submit(self, case_id: str, config: Any, clients: Any, timeout: float = 60.0):
        self._inbox.put(("run_case", (case_id, config, clients)))
        return self._outbox.get(timeout=timeout)

    def live_workers(self) -> int:
        return sum(1 for w in self._workers if w.is_alive())

    def shutdown(self, timeout: float = 10.0) -> None:
        for _ in self._workers:
            self._inbox.put(_SHUTDOWN)
        for w in self._workers:
            w.join(timeout=timeout)
            if w.is_alive():  # pragma: no cover - only if a worker wedged
                w.terminate()
                w.join(timeout=timeout)
