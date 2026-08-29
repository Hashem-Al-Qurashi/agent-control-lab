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

Uses the "spawn" start method, so any script constructing an AgentPool must
guard construction behind `if __name__ == "__main__":`. Fork would not need
that, but fork also copies the parent's memory -- including anything a previous
case left behind -- which is the leak this design exists to prevent. Pytest
satisfies the guard already; standalone scripts do not.

Known cost: the pool is currently created and torn down per schedule run, so
its lifecycle is paid on every run. That is fine at Stage 0 volumes and is the
first thing to hoist if a naturalistic mode ever runs thousands of cases. See
docs/adr/003-scaling-limits.md.
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
        try:
            _run_job(job, outbox)
        except BaseException as exc:  # noqa: BLE001
            # Nothing may escape without a result. An exception raised while
            # setting a job up -- before its own error handling -- used to kill
            # the worker silently, and collect() then blocked forever. A hang is
            # strictly worse than a failure: it hides which schedule broke and
            # burns the whole suite instead of one test.
            actor = "unknown"
            if isinstance(job, tuple) and isinstance(job[1], dict):
                actor = job[1].get("actor_id", "unknown")
            outbox.put(("error", actor, f"worker crashed: {type(exc).__name__}: {exc}"))


def _run_job(job, outbox: mp.Queue) -> None:
        kind, payload = job
        if kind == "echo_pid":
            outbox.put(os.getpid())
        elif kind == "run_redeliver":
            # Models an at-least-once bus re-offering applied events, at a moment
            # the schedule chooses rather than one it hopes for.
            import httpx as _httpx

            spec = payload
            try:
                for url in (spec["billing_url"], spec["ledger_url"]):
                    _httpx.post(
                        f"{url}/events/redeliver",
                        params={"case_id": spec["case_id"]},
                        headers={
                            "X-Actor-Id": spec["actor_id"],
                            "X-Schedule-Id": spec["schedule_id"],
                        },
                        timeout=30.0,
                    ).raise_for_status()
                outbox.put(("ok", spec["actor_id"], "redelivered"))
            except Exception as exc:
                outbox.put(("error", spec["actor_id"], f"{type(exc).__name__}: {exc}"))

        elif kind == "run_projector":
            # The projector is a scheduled actor, not a background timer. That is
            # what lets a schedule decide whether the projection catches up
            # before or after another agent reads it -- the difference between a
            # stale view and a current one, made deterministic instead of raced.
            from apps.crm.main import HttpEventSource
            from apps.crm.projector import apply_pending
            from libs.barrier.client import BarrierClient
            from libs.barrier.middleware import actor_identity

            spec = payload
            barrier = (
                BarrierClient(spec["coordinator_url"])
                if spec.get("coordinator_url")
                else None
            )
            try:
                with actor_identity(spec["actor_id"], spec["schedule_id"]):
                    sources = {
                        "billing": HttpEventSource(
                            spec["billing_url"], spec["actor_id"],
                            spec["schedule_id"],
                        ),
                        "ledger": HttpEventSource(
                            spec["ledger_url"], spec["actor_id"],
                            spec["schedule_id"],
                        ),
                    }
                    applied = apply_pending(
                        sources,
                        checkpoint=(
                            barrier.checkpoint if barrier else (lambda _n: None)
                        ),
                        order=spec.get("projection_order"),
                    )
                outbox.put(("ok", spec["actor_id"], f"applied={applied}"))
            except Exception as exc:
                outbox.put(("error", spec["actor_id"], f"{type(exc).__name__}: {exc}"))
            finally:
                if barrier is not None:
                    barrier.close()

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

            from libs.identity import issue_token

            tenant = spec.get("tenant", "acme")
            # Scoped to what this actor does, including approval authority so
            # amounts above the single-action threshold are properly authorized
            # rather than merely unenforced.
            # Scopes come from the schedule when it names them, so a schedule
            # can withhold approval authority and prove authorization prevents
            # the action rather than merely permitting everything.
            token = issue_token(
                spec["actor_id"],
                # `or`, not .get(default): the runner always sets this key, so a
                # default would never apply when the value is None.
                spec.get("scopes")
                or [
                    "refund:create", "refund:approved",
                    "credit:create", "credit:approved",
                ],
                tenant,
            )
            billing = HttpServiceClient(
                spec["billing_url"], "refunds", token=token, tenant=tenant
            )
            ledger = HttpServiceClient(
                spec["ledger_url"], "credits", token=token, tenant=tenant
            )
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
            # The read model the agent was given, when the schedule supplies one.
            crm = (
                HttpServiceClient(
                    spec["crm_url"], "compensation", token=token, tenant=tenant
                )
                if spec.get("crm_url")
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
                        **({"crm": crm} if crm else {}),
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
                if crm is not None:
                    crm.close()
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

    def dispatch_projector(self, spec: dict) -> None:
        self._inbox.put(("run_projector", spec))

    def dispatch_redeliver(self, spec: dict) -> None:
        self._inbox.put(("run_redeliver", spec))

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
