"""Task 16: telling a real violation apart from a rig defect.

Two rows over the ceiling can mean two very different things:

  different idempotency keys, different actors -> two genuinely distinct
      decisions each individually valid. That is the finding.

  the same idempotency key twice -> one logical decision that produced two
      economic effects. That is broken service idempotency: a defect in the rig,
      not a property of the architecture.

Reporting the second as a VIOLATION would be the single most damaging false
positive available, because it is the exact shape of the result being claimed.
It is reported INCONCLUSIVE instead, and an inconclusive run is not evidence
of anything.

This is also what stops P3 going green for the wrong reason.
"""

from decimal import Decimal

import psycopg2
import pytest

from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from apps.ledger.db import run_migrations as ledger_migrations
from apps.ledger.db import truncate_all as ledger_truncate
from oracle.invariants import Verdict, evaluate
from oracle.quiescence import OWNER_DSNS, grant_readonly

CEILING = Decimal("1000.00")
TABLES = {"billing": "refunds", "ledger": "credits"}


@pytest.fixture()
def clean_dbs():
    billing_migrations()
    ledger_migrations()
    grant_readonly()
    billing_truncate()
    ledger_truncate()
    yield
    billing_truncate()
    ledger_truncate()


def _plant(service, case_id, actor, amount, state, key):
    conn = psycopg2.connect(OWNER_DSNS[service])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {TABLES[service]} "
                "(case_id, actor_id, idempotency_key, amount, state) "
                "VALUES (%s, %s, %s, %s, %s)",
                (case_id, actor, key, amount, state),
            )
        conn.commit()
    finally:
        conn.close()


def test_distinct_keys_from_distinct_actors_over_budget_is_a_violation(clean_dbs):
    """The real finding: two individually valid decisions, aggregate wrong."""
    _plant("billing", "c1", "A", "600.00", "COMMITTED", "key-a")
    _plant("ledger", "c1", "B", "500.00", "COMMITTED", "key-b")

    result = evaluate("c1", CEILING)

    assert result.verdict is Verdict.VIOLATION
    assert result.realized_overage == Decimal("100.00")


def test_same_idempotency_key_twice_is_inconclusive_not_a_violation(clean_dbs):
    """A duplicated key means the service's idempotency broke -- a rig defect."""
    _plant("billing", "c1", "A", "600.00", "COMMITTED", "dup-key")
    # Same logical operation recorded twice. Only reachable if service
    # idempotency failed, which invalidates the run rather than proving anything.
    _plant("ledger", "c1", "A", "600.00", "COMMITTED", "dup-key")

    result = evaluate("c1", CEILING)

    assert result.verdict is Verdict.INCONCLUSIVE
    assert "idempotency" in (result.reason or "").lower()


def test_duplicate_key_is_inconclusive_even_when_under_the_ceiling(clean_dbs):
    """A broken rig invalidates the run whether or not the sum happens to pass."""
    _plant("billing", "c1", "A", "100.00", "COMMITTED", "dup-key")
    _plant("ledger", "c1", "A", "100.00", "COMMITTED", "dup-key")

    assert evaluate("c1", CEILING).verdict is Verdict.INCONCLUSIVE


def test_duplicate_key_within_one_service_is_inconclusive(clean_dbs):
    """Belt and braces: the UNIQUE constraint should prevent this, so if it is
    ever observed the rig is broken in a way worth halting for."""
    conn = psycopg2.connect(OWNER_DSNS["billing"])
    try:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE refunds DROP CONSTRAINT refunds_idempotency_key_key")
        conn.commit()
        _plant("billing", "c1", "A", "600.00", "COMMITTED", "dup-key")
        _plant("billing", "c1", "A", "600.00", "COMMITTED", "dup-key")

        assert evaluate("c1", CEILING).verdict is Verdict.INCONCLUSIVE
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM refunds")
            cur.execute(
                "ALTER TABLE refunds ADD CONSTRAINT refunds_idempotency_key_key "
                "UNIQUE (idempotency_key)"
            )
        conn.commit()
        conn.close()


def test_voided_duplicate_does_not_trigger_inconclusive(clean_dbs):
    """A voided row is not an economic effect, so it cannot be a double effect."""
    _plant("billing", "c1", "A", "600.00", "COMMITTED", "dup-key")
    _plant("ledger", "c1", "A", "600.00", "VOIDED", "dup-key")

    assert evaluate("c1", CEILING).verdict is Verdict.CLEAN
