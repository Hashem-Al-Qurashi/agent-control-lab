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
        elif kind == "run_diligent":
            # Everything is imported and constructed inside the worker, so no
            # configuration is captured at parent import time and nothing
            # unpicklable has to cross the process boundary.
            from decimal import Decimal

            from agents.diligent.clients import HttpServiceClient, ReservationClient
            from agents.diligent.policy import CaseConfig, Clients, run_case
            from libs.barrier.middleware import actor_identity

            spec = payload
            from libs.barrier.client import BarrierClient

            billing = HttpServiceClient(spec["billing_url"], "refunds")
            ledger = HttpServiceClient(spec["ledger_url"], "credits")
            barrier = (
                BarrierClient(spec["coordinator_url"])
                if spec.get("coordinator_url")
                else None
            )
            control = (
                ReservationClient(spec["control_url"])
                if spec.get("control_url")
                else None
            )
            config = CaseConfig(
                case_id=spec["case_id"],
                actor_id=spec["actor_id"],
                schedule_id=spec["schedule_id"],
                action=spec["action"],
                amount=Decimal(spec["amount"]),
                idempotency_key=spec["idempotency_key"],
                authorized_compensation=Decimal(spec["authorized_compensation"]),
                retry_on_failure=bool(spec.get("retry_on_failure", False)),
            )
            try:
                with actor_identity(spec["actor_id"], spec["schedule_id"]):
                    clients = Clients(
                        billing,
                        ledger,
                        checkpoint=(
                            barrier.checkpoint if barrier else (lambda _n: None)
                        ),
                        **({"reserve": control.reserve} if control else {}),
                    )
                    run_case(spec["case_id"], config, clients)
                outbox.put(("ok", spec["actor_id"], None))
            except Exception as exc:  # surfaced, never swallowed
                outbox.put(("error", spec["actor_id"], f"{type(exc).__name__}: {exc}"))
            finally:
                billing.close()
                ledger.close()
                if barrier is not None:
                    barrier.close()
                if control is not None:
                    control.close()
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

    def dispatch_diligent(self, spec: dict) -> None:
        """Queue one actor. Non-blocking: actors must be able to run at once."""
        self._inbox.put(("run_diligent", spec))

    def collect(self, count: int, timeout: float = 120.0) -> list[tuple]:
        return [self._outbox.get(timeout=timeout) for _ in range(count)]

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
