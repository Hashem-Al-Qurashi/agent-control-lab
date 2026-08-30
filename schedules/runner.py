"""Run one named schedule end to end and return a verdict with its evidence.

Order matters and is not negotiable:

  1. clean slate, verified
  2. declare the schedule to the coordinator
  3. dispatch every actor at once, as separate OS processes
  4. wait for all actors to finish
  5. assert quiescence -- no waiter still parked
  6. only then evaluate

Step 5 before step 6 is the point. Two independent Postgres admit no
cross-database snapshot, so evaluating while an actor is still in flight yields
a torn state. And a schedule that "passes" with a waiter still parked may simply
mean the second actor never ran.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from decimal import Decimal

import httpx
import yaml

from agents.diligent.pool import AgentPool
from oracle.divergence import capture_views
from oracle.transitions import transitions as read_transitions
from oracle.invariants import Result, evaluate
from oracle.quiescence import ensure_quiescent

SCHEDULES = pathlib.Path(__file__).parent


class CorruptSample(Exception):
    """The run's own evidence was destroyed before it could be read.

    Distinct from a divergence on purpose. A replay whose money moved but whose
    decision log is empty has not behaved differently -- something truncated the
    table underneath it. ADR-007 conflated the two for the life of the project
    and spent that time suspecting the scheduler, when the barrier's release
    order had in fact been identical throughout.
    """


class ScheduleNotExecuted(Exception):
    """The run did not follow its declared interleaving, so no verdict from it
    can be attributed to the schedule."""


class ActorFailed(Exception):
    """An actor raised. Surfaced, never swallowed -- a run with a crashed actor
    is not evidence of anything about the architecture."""


@dataclass
class RunOutcome:
    schedule_id: str
    result: Result
    release_order: list
    parked_waiters: list
    actor_outcomes: list
    divergence: dict
    # Captured INSIDE the run, at quiescence, rather than read afterwards. A
    # later read can be emptied by anything that truncates these tables, and
    # that is what ADR-007 had been reporting as a replay divergence.
    transitions: list


def expected_release_order(schedule_id: str) -> list[tuple[str, str, int]]:
    """Declared steps with occurrence indices resolved, matching what the
    coordinator records."""
    from collections import Counter

    seen: Counter = Counter()
    order = []
    for actor, checkpoint in load(schedule_id)["steps"]:
        order.append((actor, checkpoint, seen[(actor, checkpoint)]))
        seen[(actor, checkpoint)] += 1
    return order


def load(schedule_id: str) -> dict:
    return yaml.safe_load((SCHEDULES / f"{schedule_id.lower()}.yaml").read_text())


def run_schedule(
    schedule_id: str, stack: dict, case_id: str | None = None
) -> RunOutcome:
    spec = load(schedule_id)
    case_id = case_id or f"case-{schedule_id.lower()}"
    coordinator = stack["coordinator"]

    httpx.post(
        f"{coordinator}/declare",
        json={
            "schedule_id": spec["schedule_id"],
            "steps": [list(step) for step in spec["steps"]],
            "timeout_seconds": spec.get("timeout_seconds", 30.0),
            "lease_ttl_seconds": spec.get("lease_ttl_seconds", 30.0),
            "faults": [list(f) for f in spec.get("faults", [])],
        },
        timeout=10.0,
    ).raise_for_status()

    pool = AgentPool(size=len(spec["actors"]))
    try:
        for actor in spec["actors"]:
            if actor["action"] == "redeliver":
                pool.dispatch_redeliver(
                    {
                        "actor_id": actor["id"],
                        "schedule_id": spec["schedule_id"],
                        "case_id": case_id,
                        "billing_url": stack["billing"],
                        "ledger_url": stack["ledger"],
                    }
                )
                continue
            if actor["action"] == "project":
                pool.dispatch_projector(
                    {
                        "actor_id": actor["id"],
                        "schedule_id": spec["schedule_id"],
                        "case_id": case_id,
                        "coordinator_url": coordinator,
                        "billing_url": stack["billing"],
                        "ledger_url": stack["ledger"],
                        "projection_order": actor.get("projection_order"),
                    }
                )
                continue
            pool.dispatch_diligent(
                {
                    "case_id": case_id,
                    "actor_id": actor["id"],
                    "schedule_id": spec["schedule_id"],
                    "action": actor["action"],
                    "amount": actor["amount"],
                    "idempotency_key": actor["idempotency_key"],
                    "retry_on_failure": actor.get("retry_on_failure", False),
                    "abandon_after_reserve": actor.get("abandon_after_reserve", False),
                    "scopes": actor.get("scopes"),
                    "authorized_compensation": spec["authorized_compensation"],
                    "billing_url": stack["billing"],
                    "coordinator_url": coordinator,
                    "control_url": (
                        stack.get("control")
                        if spec.get("use_reservations")
                        else None
                    ),
                    "crm_url": (
                        stack.get("crm") if spec.get("use_projection") else None
                    ),
                    "ledger_url": stack["ledger"],
                }
            )
        actor_outcomes = pool.collect(len(spec["actors"]))
    finally:
        pool.shutdown()

    state = httpx.get(f"{coordinator}/waiters", timeout=10.0).json()
    ensure_quiescent(state["waiters"])  # raises NotQuiescent

    return RunOutcome(
        schedule_id=spec["schedule_id"],
        result=evaluate(case_id, Decimal(spec["authorized_compensation"])),
        release_order=state["release_order"],
        parked_waiters=state["waiters"],
        actor_outcomes=actor_outcomes,
        divergence=capture_views(case_id).as_dict(),
        transitions=read_transitions(case_id),
    )


def assert_schedule_executed(outcome: RunOutcome, expected_steps) -> None:
    """Assert the declared interleaving is what actually ran.

    Gate-3 finding: with the barrier bypassed entirely, P2 still produced a
    violation -- both actors race naturally and both observe zero. So "P2
    violated" on its own does NOT establish that the schedule caused it, and a
    dead barrier would look identical to a working one.

    Every verdict claim is therefore coupled to this check. A verdict without
    evidence of the interleaving that produced it is not evidence.
    """
    actual = [tuple(r) for r in outcome.release_order]
    expected = [tuple(s) for s in expected_steps]
    if actual != expected:
        raise ScheduleNotExecuted(
            f"{outcome.schedule_id} did not execute its declared interleaving.\n"
            f"declared: {expected}\nactual:   {actual}\n"
            "The verdict above cannot be attributed to the schedule."
        )


def assert_actors_succeeded(outcome: RunOutcome) -> None:
    failures = [o for o in outcome.actor_outcomes if o[0] == "error"]
    if failures:
        raise ActorFailed(
            f"{len(failures)} actor(s) raised during {outcome.schedule_id}: "
            f"{failures}"
        )
