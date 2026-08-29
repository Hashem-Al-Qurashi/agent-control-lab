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


# reserve is None when no coordination authority exists. That absence is the
# baseline condition under test, not a degenerate case to paper over.


@dataclass(frozen=True)
class Clients:
    billing: ServiceClient
    ledger: ServiceClient
    # The integration point the agent was actually given. When present it is the
    # agent's view of what compensation exists, because in real systems an agent
    # usually cannot query another team's authoritative store -- it reads a CRM
    # or reporting view. That view lags. The agent is no less diligent for
    # trusting it; the staleness belongs to the interface, not the policy.
    crm: ServiceClient | None = None
    # Injected so the policy stays pure and unit-testable with fakes. The
    # barrier is a property of the experiment, not of the agent's logic.
    checkpoint: Callable[[str], None] = field(default=_no_checkpoint)
    # The coordination primitive. Absent in the baseline, present in P0 --
    # and that difference is the whole contrast the experiment rests on.
    # Returns a reservation id when granted, None when refused.
    reserve: Callable[..., int | None] | None = None
    # Compensation. Reserving is only safe if un-reserving is guaranteed on
    # the paths where the effect never lands -- otherwise the hardened arm
    # trades over-spending for invisible under-spending, which looks exactly
    # like the control working correctly.
    release: Callable[[int], None] | None = None
    commit: Callable[[int], None] | None = None


@dataclass(frozen=True)
class CaseConfig:
    case_id: str
    actor_id: str
    schedule_id: str
    action: str  # "refund" -> billing, "credit" -> ledger
    amount: Decimal
    idempotency_key: str
    authorized_compensation: Decimal
    # An explicit, keyed decision -- never automatic. An automatic resend on
    # a non-idempotent endpoint is indistinguishable from two agents racing.
    retry_on_failure: bool = False


def observed_compensation(case_id: str, clients: Clients) -> Decimal:
    """Read everything the agent has access to. Order is fixed so schedules can
    name it.

    When a CRM view is supplied, that IS the access the agent has -- it does not
    also read the authoritative stores, because modelling an agent with access
    it would not have in production would make the staleness unreachable and the
    experiment uninteresting.
    """
    if clients.crm is not None:
        return clients.crm.total_committed(case_id)
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

    reservation_id = None
    if clients.reserve is not None:
        # Ordering the reservation explicitly. Releasing two actors in a known
        # order does NOT determine which of them reaches the control service
        # first -- release order is not execution order. Without a checkpoint
        # here the winner would be decided by scheduling luck, which is exactly
        # the nondeterminism this harness exists to eliminate.
        clients.checkpoint("agent.before_reserve")

        # The only difference between P2 and P0: same policy, same interleaving,
        # but an interface that can see the aggregate.
        reservation_id = clients.reserve(
            case_id,
            config.amount,
            config.idempotency_key,
            config.authorized_compensation,
        )
        if reservation_id is None:
            return

    target = clients.billing if config.action == "refund" else clients.ledger
    try:
        try:
            target.create(case_id, config.amount, config.idempotency_key)
        except Exception:
            if not config.retry_on_failure:
                raise
            # Outcome ambiguous: the effect may or may not be durable. Retrying
            # with the SAME idempotency key is the correct response -- it either
            # completes the operation or returns the one already recorded, never
            # a second one.
            target.create(case_id, config.amount, config.idempotency_key)
    except Exception:
        # The effect did not land. Free the budget it was holding, then let the
        # failure propagate: swallowing it here would look like a decline and
        # the run would draw a wrong conclusion.
        if reservation_id is not None and clients.release is not None:
            clients.release(reservation_id)
        raise

    if reservation_id is not None and clients.commit is not None:
        clients.commit(reservation_id)
