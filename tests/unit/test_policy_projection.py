"""Stage 1: the agent reads the integration point it was given.

Stage 0's agent read Billing and Ledger directly and saw truth. That is not the
common real shape. An agent usually cannot query another team's authoritative
store -- it reads a CRM or reporting view, because that is the integration that
exists.

So when a CRM view is supplied, it becomes the agent's source for what
compensation exists. The agent is no less diligent: it reads everything it has
access to and decides correctly from it. The staleness is a property of the
interface, not a lapse in the policy -- which is the same distinction P0 drew,
now one level up.

If the agent could read the authoritative stores, this would be a different and
much less interesting experiment.
"""

from decimal import Decimal

from agents.diligent.policy import CaseConfig, Clients, run_case

CEILING = Decimal("1000.00")


class FakeService:
    def __init__(self, committed=Decimal("0.00")):
        self._committed = committed
        self.reads = []
        self.creates = []

    def total_committed(self, case_id):
        self.reads.append(case_id)
        return self._committed

    def create(self, case_id, amount, idempotency_key):
        self.creates.append((case_id, amount, idempotency_key))
        return {"id": len(self.creates), "state": "COMMITTED"}


class FakeProjection:
    def __init__(self, total=Decimal("0.00")):
        self._total = total
        self.reads = []

    def total_committed(self, case_id):
        self.reads.append(case_id)
        return self._total


def _config(action="credit", amount="500.00"):
    return CaseConfig(
        case_id="c1", actor_id="B", schedule_id="S1", action=action,
        amount=Decimal(amount), idempotency_key="k1",
        authorized_compensation=CEILING,
    )


def test_projection_becomes_the_compensation_view_when_supplied():
    billing, ledger = FakeService(), FakeService()
    crm = FakeProjection(total=Decimal("600.00"))

    run_case("c1", _config(), Clients(billing, ledger, crm=crm))

    assert crm.reads == ["c1"]
    assert ledger.creates == [], "600 + 500 exceeds 1000; the agent must decline"


def test_a_stale_projection_leads_to_a_locally_correct_but_wrong_decision():
    """The thesis, in miniature.

    Authoritative state is 600. The projection has not caught up and reports 0.
    The agent reads what it was given, decides correctly from it, and acts --
    producing an aggregate of 1100.
    """
    billing = FakeService(committed=Decimal("600.00"))  # truth
    ledger = FakeService()
    crm = FakeProjection(total=Decimal("0.00"))         # stale view

    run_case("c1", _config(amount="500.00"), Clients(billing, ledger, crm=crm))

    assert ledger.creates == [("c1", Decimal("500.00"), "k1")], (
        "the agent should act -- its view said 0, and 0 + 500 is under the "
        "ceiling. The decision is correct given what it could see."
    )


def test_without_a_projection_the_agent_reads_the_authoritative_stores():
    """Stage 0 behaviour is unchanged when no CRM view is supplied."""
    billing = FakeService(committed=Decimal("600.00"))
    ledger = FakeService()

    run_case("c1", _config(amount="500.00"), Clients(billing, ledger))

    assert billing.reads == ["c1"] and ledger.reads == ["c1"]
    assert ledger.creates == [], "sees 600 directly, so must decline"


def test_agent_does_not_also_read_authoritative_stores_when_given_a_projection():
    """It reads the interface it has, not one it does not.

    Reading both would model an agent with access it would not have, and would
    quietly make the staleness unreachable.
    """
    billing, ledger = FakeService(), FakeService()
    crm = FakeProjection(total=Decimal("0.00"))

    run_case("c1", _config(), Clients(billing, ledger, crm=crm))

    assert billing.reads == [] and ledger.reads == []
