"""Task 17: record what the API said alongside what was true.

The agent reads through the service APIs -- that is what a real agent has. The
oracle reads the databases directly. When those two views disagree, the gap is
itself a result: the system reported success while the business state was
already wrong.

Divergence is recorded and reported, never silently reconciled. Quietly
preferring one number would destroy the only evidence that the system's own
account of itself was unreliable.
"""

from decimal import Decimal

import psycopg2
import pytest

from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from apps.ledger.db import run_migrations as ledger_migrations
from apps.ledger.db import truncate_all as ledger_truncate
from oracle.divergence import capture_views
from oracle.quiescence import OWNER_DSNS, grant_readonly

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


def test_no_divergence_when_api_and_truth_agree(clean_dbs):
    _plant("billing", "c1", "A", "600.00", "COMMITTED", "k1")
    _plant("ledger", "c1", "B", "500.00", "COMMITTED", "k2")

    view = capture_views("c1")

    assert view.sql_total == Decimal("1100.00")
    assert view.api_total == Decimal("1100.00")
    assert view.diverged is False
    assert view.delta == Decimal("0")


def test_divergence_is_detected_and_both_numbers_kept(clean_dbs):
    """The deliverable artifact: 'the API reported X while truth was Y'."""
    _plant("billing", "c1", "A", "600.00", "COMMITTED", "k1")
    _plant("ledger", "c1", "B", "500.00", "COMMITTED", "k2")

    # An API that under-reports -- the shape of a stale read model or a filter bug.
    def understating_api(case_id):
        return Decimal("600.00")

    view = capture_views("c1", api_reader=understating_api)

    assert view.diverged is True
    assert view.api_total == Decimal("600.00")
    assert view.sql_total == Decimal("1100.00")
    assert view.delta == Decimal("500.00")


def test_divergence_is_not_silently_reconciled(clean_dbs):
    """Both numbers survive into the record. Preferring one destroys the evidence."""
    _plant("billing", "c1", "A", "600.00", "COMMITTED", "k1")

    view = capture_views("c1", api_reader=lambda _: Decimal("0.00"))
    record = view.as_dict()

    assert record["api_total"] == "0.00"
    assert record["sql_total"] == "600.00"
    assert record["diverged"] is True


def test_divergence_summary_is_human_readable(clean_dbs):
    _plant("billing", "c1", "A", "600.00", "COMMITTED", "k1")
    _plant("ledger", "c1", "B", "500.00", "COMMITTED", "k2")

    view = capture_views("c1", api_reader=lambda _: Decimal("600.00"))

    assert "600.00" in view.summary
    assert "1100.00" in view.summary


def test_api_over_reporting_also_counts_as_divergence(clean_dbs):
    """Direction-agnostic: the API claiming more than is true is equally a defect."""
    _plant("billing", "c1", "A", "600.00", "COMMITTED", "k1")

    view = capture_views("c1", api_reader=lambda _: Decimal("900.00"))

    assert view.diverged is True
    assert view.delta == Decimal("300.00")
