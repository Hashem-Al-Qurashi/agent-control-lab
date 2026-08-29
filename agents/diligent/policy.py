"""The diligent deterministic policy.

Pre-registered definition of "diligent", so no reviewer can name something the
agent could have done with the tools it was given:

  1. read EVERY authoritative system relevant to the invariant
  2. normalise their economic effects into one total
  3. check the requested action against the ceiling using that total
  4. act only if the invariant still holds given what was observed

If the agent only consulted its own service, the finding would reduce to "it
didn't look". The interesting version is that a policy doing everything a
careful engineer would do can still be defeated, because its read and its write
are not atomic across independent transaction boundaries.

No LLM. Nondeterminism here would contaminate the structural result -- the point
of this arm is that failure cannot be blamed on the model.

No module-level mutable state and no import-time environment reads: one
pre-warmed interpreter serves many cases, and anything cached at import would
leak between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Protocol


class ServiceClient(Protocol):
    def total_committed(self, case_id: str) -> Decimal: ...

    def create(
        self, case_id: str, amount: Decimal, idempotency_key: str
    ) -> dict: ...


def _no_checkpoint(name: str) -> None:
    """Default: the policy does not participate in any schedule."""


@dataclass(frozen=True)
class Clients:
    billing: ServiceClient
    ledger: ServiceClient
    # Injected so the policy stays pure and unit-testable with fakes. The
    # barrier is a property of the experiment, not of the agent's logic.
    checkpoint: Callable[[str], None] = field(default=_no_checkpoint)


@dataclass(frozen=True)
class CaseConfig:
    case_id: str
    actor_id: str
    schedule_id: str
    action: str  # "refund" -> billing, "credit" -> ledger
    amount: Decimal
    idempotency_key: str
    authorized_compensation: Decimal


def observed_compensation(case_id: str, clients: Clients) -> Decimal:
    """Read every authoritative system. Order is fixed so schedules can name it."""
    return clients.billing.total_committed(case_id) + clients.ledger.total_committed(
        case_id
    )


def run_case(case_id: str, config: CaseConfig, clients: Clients) -> None:
    if config.action not in ("refund", "credit"):
        # Guess nothing. An agent that invents an action would fabricate the run.
        raise ValueError(f"unknown action {config.action!r}")

    # Before any observation. Without this the schedule can order writes but
    # not reads, so an actor's view of the world is whatever it happened to see
    # -- which makes a "sequential" control not actually sequential.
    clients.checkpoint("agent.before_reads")

    observed = observed_compensation(case_id, clients)

    # The read-check-write window. Everything relevant has been observed and
    # the decision is made from it, but nothing has been written yet. This is
    # where a concurrent actor can commit and render the observation stale --
    # the gap the whole experiment is about, and it lives in the agent, not in
    # any one service.
    clients.checkpoint("agent.after_reads_before_act")

    # <= not <. The ceiling is inclusive: spending exactly the authorised amount
    # is correct, and an off-by-one here would look exactly like a violation.
    if observed + config.amount > config.authorized_compensation:
        return

    target = clients.billing if config.action == "refund" else clients.ledger
    target.create(case_id, config.amount, config.idempotency_key)
