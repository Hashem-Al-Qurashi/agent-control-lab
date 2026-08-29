"""Stage 1: transactional outbox and a barrier-gated projection consumer.

The thesis Stage 0 could not test needs propagation lag: an agent that reads
every source available to it and STILL holds a stale view, because one of those
sources is a read model that has not caught up.

That is the realistic shape. In real systems an agent frequently cannot query
the authoritative store -- it reads a CRM or a reporting view, because that is
the integration point it was given.

Determinism boundary (LAB-SPEC): the schedule does NOT control transport. It
controls the moment an event is APPLIED to business state. The consumer may
fetch whenever it likes; when CRM becomes allowed to observe the effect is ours.

Events are written in the same transaction as the effect they describe. An
outbox that can commit the effect without the event, or the event without the
effect, would produce lag that is a bug rather than a property.
"""

from decimal import Decimal

import psycopg2
import pytest

from apps.billing.db import connect as billing_connect
from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from libs.outbox import claim_unapplied, mark_applied, pending_count, publish


@pytest.fixture()
def clean_billing():
    billing_migrations()
    billing_truncate()
    yield
    billing_truncate()


def test_event_and_effect_commit_atomically(clean_billing):
    """Both or neither. A partial commit makes lag a bug, not a property."""
    with billing_connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO refunds (case_id, actor_id, idempotency_key, amount, state) "
            "VALUES ('c1','A','k1','600.00','COMMITTED') RETURNING id"
        )
        refund_id = cur.fetchone()[0]
        publish(cur, case_id="c1", actor_id="A", service="billing",
                event_type="RefundCommitted", entity_id=refund_id,
                amount=Decimal("600.00"))
        conn.commit()

    assert pending_count(billing_connect) == 1


def test_rollback_discards_both_effect_and_event(clean_billing):
    conn = psycopg2.connect(
        "postgresql://billing:billing@127.0.0.1:55433/billing"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO refunds (case_id, actor_id, idempotency_key, amount, "
                "state) VALUES ('c1','A','k9','600.00','COMMITTED') RETURNING id"
            )
            refund_id = cur.fetchone()[0]
            publish(cur, case_id="c1", actor_id="A", service="billing",
                    event_type="RefundCommitted", entity_id=refund_id,
                    amount=Decimal("600.00"))
        conn.rollback()
    finally:
        conn.close()

    assert pending_count(billing_connect) == 0
    with billing_connect() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM refunds")
        assert cur.fetchone()[0] == 0


def test_unapplied_events_are_claimed_in_publication_order(clean_billing):
    with billing_connect() as conn, conn.cursor() as cur:
        for i, amount in enumerate(["100.00", "200.00", "300.00"]):
            cur.execute(
                "INSERT INTO refunds (case_id, actor_id, idempotency_key, amount, "
                "state) VALUES ('c1','A',%s,%s,'COMMITTED') RETURNING id",
                (f"k{i}", amount),
            )
            publish(cur, case_id="c1", actor_id="A", service="billing",
                    event_type="RefundCommitted", entity_id=cur.fetchone()[0],
                    amount=Decimal(amount))
        conn.commit()

    claimed = claim_unapplied(billing_connect, limit=10)
    assert [str(e["amount"]) for e in claimed] == ["100.00", "200.00", "300.00"]


def test_applied_events_are_not_reclaimed(clean_billing):
    with billing_connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO refunds (case_id, actor_id, idempotency_key, amount, state) "
            "VALUES ('c1','A','k1','600.00','COMMITTED') RETURNING id"
        )
        publish(cur, case_id="c1", actor_id="A", service="billing",
                event_type="RefundCommitted", entity_id=cur.fetchone()[0],
                amount=Decimal("600.00"))
        conn.commit()

    first = claim_unapplied(billing_connect, limit=10)
    assert len(first) == 1
    mark_applied(billing_connect, [first[0]["id"]])

    assert claim_unapplied(billing_connect, limit=10) == []
    assert pending_count(billing_connect) == 0


def test_pending_count_is_the_lag_measure(clean_billing):
    """Lag must be observable. An unmeasurable lag cannot be reported as a
    condition of a result."""
    assert pending_count(billing_connect) == 0

    with billing_connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO refunds (case_id, actor_id, idempotency_key, amount, state) "
            "VALUES ('c1','A','k1','600.00','COMMITTED') RETURNING id"
        )
        publish(cur, case_id="c1", actor_id="A", service="billing",
                event_type="RefundCommitted", entity_id=cur.fetchone()[0],
                amount=Decimal("600.00"))
        conn.commit()

    assert pending_count(billing_connect) == 1
