"""Stage 1: the schedule controls which source is folded in first.

Needed to isolate a confound. A reviewer looking at S1 can reasonably ask
whether the breach depends on the ORDER events are applied in, rather than on
the lag. If order mattered, "the projection was behind" would be an incomplete
explanation.

Sum is commutative, so it should not matter -- but should-not is an assumption
until it is measured, and this harness exists because assumptions about
concurrent systems are usually wrong.

Redelivery is separate: an at-least-once bus offers an event again after it was
applied. The projection must absorb that without double-counting, because a
double count fabricates a violation out of nothing.
"""

from decimal import Decimal

import pytest

from apps.crm.db import run_migrations, truncate_all
from apps.crm.projector import apply_pending, projection_total


class FakeSource:
    def __init__(self, service, events):
        self.service = service
        self._events = list(events)
        self.marked = []

    def unapplied(self):
        return [e for e in self._events if e["id"] not in self.marked]

    def mark_applied(self, event_id):
        self.marked.append(event_id)

    def redeliver(self):
        """An at-least-once bus offering an already-applied event again."""
        self.marked.clear()


def _event(eid, amount, service):
    return {"id": eid, "case_id": "c1", "actor_id": "A", "service": service,
            "event_type": "Committed", "entity_id": eid, "amount": amount}


@pytest.fixture()
def clean_crm():
    run_migrations()
    truncate_all()
    yield
    truncate_all()


def test_default_order_is_declared_not_incidental(clean_crm):
    billing = FakeSource("billing", [_event(1, "600.00", "billing")])
    ledger = FakeSource("ledger", [_event(1, "500.00", "ledger")])

    applied = apply_pending({"billing": billing, "ledger": ledger})

    assert applied == 2
    assert projection_total("c1") == Decimal("1100.00")


def test_reversed_order_produces_the_same_total(clean_crm):
    """Isolates the confound: the breach is about lag, not ordering."""
    billing = FakeSource("billing", [_event(1, "600.00", "billing")])
    ledger = FakeSource("ledger", [_event(1, "500.00", "ledger")])

    apply_pending(
        {"billing": billing, "ledger": ledger}, order=["ledger", "billing"]
    )

    assert projection_total("c1") == Decimal("1100.00")


def test_order_changes_which_checkpoint_fires_first(clean_crm):
    """The order must be observable, or the schedule cannot depend on it."""
    seen = []
    billing = FakeSource("billing", [_event(1, "600.00", "billing")])
    ledger = FakeSource("ledger", [_event(1, "500.00", "ledger")])

    def checkpoint(name):
        seen.append((name, projection_total("c1")))

    apply_pending(
        {"billing": billing, "ledger": ledger},
        checkpoint=checkpoint,
        order=["ledger", "billing"],
    )

    applies = [total for name, total in seen if name == "crm.before_apply_event"]
    # Ledger's 500 lands first, so the second apply sees 500 already present.
    assert applies == [Decimal("0"), Decimal("500.00")]


def test_an_unknown_source_in_the_order_is_rejected(clean_crm):
    """Fail closed. Silently skipping an unknown name would drop events."""
    billing = FakeSource("billing", [_event(1, "600.00", "billing")])

    with pytest.raises(KeyError):
        apply_pending({"billing": billing}, order=["ledger"])


def test_redelivery_after_a_successful_apply_does_not_double_count(clean_crm):
    """At-least-once delivery must not inflate the projection.

    A double-counted event fabricates a violation out of nothing -- the worst
    available false positive, because it has the shape of the real result.
    """
    billing = FakeSource("billing", [_event(1, "600.00", "billing")])
    apply_pending({"billing": billing})
    assert projection_total("c1") == Decimal("600.00")

    billing.redeliver()
    apply_pending({"billing": billing})

    assert projection_total("c1") == Decimal("600.00")


def test_redelivery_still_marks_the_source_applied(clean_crm):
    """Otherwise the event is offered forever and the lag never clears."""
    billing = FakeSource("billing", [_event(1, "600.00", "billing")])
    apply_pending({"billing": billing})
    billing.redeliver()

    apply_pending({"billing": billing})

    assert billing.marked == [1]
