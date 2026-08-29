"""Task 11: the diligent deterministic policy.

"Diligent" is a pre-registered, testable definition, not a vibe. The agent reads
EVERY authoritative system relevant to the invariant, sums the observed
compensation, and acts only if the invariant still holds given what it observed.

This matters for the eventual claim. If the agent only checked its own service,
the finding reduces to "the agent didn't look" -- boring and correct. The
interesting version is that a policy which does everything a careful engineer
would do can still be defeated, because its read and its write are not atomic
across independent transaction boundaries.

No LLM. Any nondeterminism here would contaminate the structural result.
"""

from decimal import Decimal

import pytest

from agents.diligent.policy import CaseConfig, Clients, run_case

CEILING = Decimal("1000.00")


class FakeService:
    def __init__(self, committed=Decimal("0.00")):
        self._committed = committed
        self.reads: list[str] = []
        self.creates: list[tuple] = []

    def total_committed(self, case_id: str) -> Decimal:
        self.reads.append(case_id)
        return self._committed

    def create(self, case_id, amount, idempotency_key) -> dict:
        self.creates.append((case_id, amount, idempotency_key))
        return {"id": len(self.creates), "state": "COMMITTED"}


def _config(action="refund", amount="500.00"):
    return CaseConfig(
        case_id="case-1",
        actor_id="A",
        schedule_id="P1",
        action=action,
        amount=Decimal(amount),
        idempotency_key="k1",
        authorized_compensation=CEILING,
    )


def test_acts_when_the_invariant_still_holds():
    billing, ledger = FakeService(), FakeService()
    run_case("case-1", _config(amount="600.00"), Clients(billing, ledger))

    assert billing.creates == [("case-1", Decimal("600.00"), "k1")]
    assert ledger.creates == []


def test_declines_when_the_action_would_breach_the_ceiling():
    billing = FakeService(committed=Decimal("600.00"))
    ledger = FakeService()

    run_case("case-1", _config(amount="500.00"), Clients(billing, ledger))

    assert billing.creates == [], "acted despite observing a breach"


def test_declines_on_a_breach_spread_across_both_services():
    """The sum is what matters, not either service's own total."""
    billing = FakeService(committed=Decimal("400.00"))
    ledger = FakeService(committed=Decimal("400.00"))

    run_case("case-1", _config(amount="300.00"), Clients(billing, ledger))

    assert billing.creates == []


def test_acts_exactly_at_the_ceiling():
    """<= not <. A boundary error here would look like a violation."""
    billing = FakeService(committed=Decimal("400.00"))
    ledger = FakeService(committed=Decimal("100.00"))

    run_case("case-1", _config(amount="500.00"), Clients(billing, ledger))

    assert billing.creates == [("case-1", Decimal("500.00"), "k1")]


def test_reads_both_services_before_every_decision():
    """The definition of diligent. If this fails, the finding is 'it didn't look'."""
    billing, ledger = FakeService(), FakeService()
    run_case("case-1", _config(), Clients(billing, ledger))

    assert billing.reads == ["case-1"]
    assert ledger.reads == ["case-1"]


def test_reads_happen_before_the_write():
    order: list[str] = []

    class Recording(FakeService):
        def __init__(self, name, committed=Decimal("0.00")):
            super().__init__(committed)
            self.name = name

        def total_committed(self, case_id):
            order.append(f"read:{self.name}")
            return super().total_committed(case_id)

        def create(self, case_id, amount, idempotency_key):
            order.append(f"write:{self.name}")
            return super().create(case_id, amount, idempotency_key)

    billing, ledger = Recording("billing"), Recording("ledger")
    run_case("case-1", _config(), Clients(billing, ledger))

    assert order == ["read:billing", "read:ledger", "write:billing"]


def test_credit_action_targets_the_ledger():
    billing, ledger = FakeService(), FakeService()
    run_case("case-1", _config(action="credit"), Clients(billing, ledger))

    assert ledger.creates == [("case-1", Decimal("500.00"), "k1")]
    assert billing.creates == []


def test_unknown_action_raises_rather_than_guessing():
    billing, ledger = FakeService(), FakeService()
    with pytest.raises(ValueError):
        run_case("case-1", _config(action="teleport"), Clients(billing, ledger))
