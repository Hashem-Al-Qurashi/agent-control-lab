"""Stage 1: the projection consumer, and where its checkpoint sits.

Determinism boundary (LAB-SPEC): the schedule does not control transport. The
consumer may fetch whenever it likes. What the schedule controls is the moment
an event is APPLIED to business state -- when CRM becomes allowed to observe the
effect.

So the checkpoint is inside the consumer, BEFORE the projection mutates. A
checkpoint after the apply would order nothing that matters: by then the agent
reading CRM would already see the new value.

Double-counting is the failure that would fabricate a violation, so re-delivery
is guarded by the source's own event id rather than by hoping delivery is
exactly-once.
"""

from decimal import Decimal

import pytest

from apps.crm.db import connect, run_migrations, truncate_all
from apps.crm.projector import apply_pending, projection_total


class FakeSource:
    """Stands in for a service's /events endpoint."""

    def __init__(self, service, events):
        self.service = service
        self._events = list(events)
        self.marked = []

    def unapplied(self):
        return [e for e in self._events if e["id"] not in self.marked]

    def mark_applied(self, event_id):
        self.marked.append(event_id)


def _event(eid, case_id="c1", amount="600.00", service="billing"):
    return {"id": eid, "case_id": case_id, "actor_id": "A", "service": service,
            "event_type": "RefundCommitted", "entity_id": eid, "amount": amount}


@pytest.fixture()
def clean_crm():
    run_migrations()
    truncate_all()
    yield
    truncate_all()


def test_applying_an_event_advances_the_projection(clean_crm):
    src = FakeSource("billing", [_event(1)])
    applied = apply_pending({"billing": src})

    assert applied == 1
    assert projection_total("c1") == Decimal("600.00")


def test_projection_is_stale_until_the_event_is_applied(clean_crm):
    """The lag, stated as a test. This is the whole Stage 1 mechanism."""
    src = FakeSource("billing", [_event(1)])

    assert projection_total("c1") == Decimal("0"), (
        "projection should not reflect an unapplied event"
    )

    apply_pending({"billing": src})
    assert projection_total("c1") == Decimal("600.00")


def test_redelivery_does_not_double_count(clean_crm):
    """A double-counted event would fabricate a violation out of nothing."""
    src = FakeSource("billing", [_event(1)])
    apply_pending({"billing": src})

    # Same event offered again, as an at-least-once bus would.
    src.marked.clear()
    apply_pending({"billing": src})

    assert projection_total("c1") == Decimal("600.00")


def test_events_from_both_services_accumulate(clean_crm):
    billing = FakeSource("billing", [_event(1, amount="600.00")])
    ledger = FakeSource("ledger", [_event(1, amount="500.00", service="ledger")])

    apply_pending({"billing": billing, "ledger": ledger})

    assert projection_total("c1") == Decimal("1100.00")


def test_same_source_id_from_different_services_are_distinct(clean_crm):
    """Event ids are only unique within a service. Keying on id alone would
    silently drop one of these."""
    billing = FakeSource("billing", [_event(1, amount="600.00")])
    ledger = FakeSource("ledger", [_event(1, amount="500.00", service="ledger")])

    apply_pending({"billing": billing})
    apply_pending({"ledger": ledger})

    assert projection_total("c1") == Decimal("1100.00")


def test_checkpoint_fires_before_each_apply(clean_crm):
    """Ordering the apply is what makes staleness schedulable."""
    seen = []
    src = FakeSource("billing", [_event(1, amount="600.00")])

    def checkpoint(name):
        seen.append((name, projection_total("c1")))

    apply_pending({"billing": src}, checkpoint=checkpoint)

    assert seen == [("crm.before_apply_event", Decimal("0"))], (
        "checkpoint must fire while the projection is still stale; firing after "
        "the apply would order nothing an agent could observe"
    )


def test_source_is_marked_applied_only_after_the_projection_commits(clean_crm):
    src = FakeSource("billing", [_event(1)])
    apply_pending({"billing": src})

    assert src.marked == [1]
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM applied_events")
        assert cur.fetchone()[0] == 1
