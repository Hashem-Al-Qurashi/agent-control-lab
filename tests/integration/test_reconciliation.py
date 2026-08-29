"""Stage 1: the reconciler the baseline is entitled to.

LAB-SPEC's baseline credibility standard requires competent DETECTION, not just
competent controls. Without a real reconciler, "the violation went undetected"
would be manufactured -- of course nothing caught it, nothing was looking.

The boundary matters and is deliberate. The reconciler looks for GENERIC
anomalies a competent team would monitor: a projection lagging, a projection
that drifted from the events it applied, duplicate idempotency keys, orphaned
applied-events. It does NOT check the aggregate ceiling. That check is the
solution under test -- handing it to the baseline would be assuming the answer.

So the question these tests ask is the honest one: does ordinary monitoring
surface a business-invariant breach? The expected answer is no, and that is the
finding rather than an accident.
"""

from decimal import Decimal

import psycopg2
import pytest

from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from apps.crm.db import run_migrations as crm_migrations
from apps.crm.db import truncate_all as crm_truncate
from apps.ledger.db import run_migrations as ledger_migrations
from apps.ledger.db import truncate_all as ledger_truncate
from apps.reconciliation.worker import FindingType, reconcile
from oracle.quiescence import OWNER_DSNS

CRM_DSN = "postgresql://crm:crm@127.0.0.1:55436/crm"
TABLES = {"billing": "refunds", "ledger": "credits"}


@pytest.fixture()
def clean():
    billing_migrations(); ledger_migrations(); crm_migrations()
    billing_truncate(); ledger_truncate(); crm_truncate()
    yield
    billing_truncate(); ledger_truncate(); crm_truncate()


def _commit(service, case_id, actor, amount, key, with_event=True):
    conn = psycopg2.connect(OWNER_DSNS[service])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {TABLES[service]} (case_id, actor_id, "
                "idempotency_key, amount, state) VALUES (%s,%s,%s,%s,'COMMITTED') "
                "RETURNING id",
                (case_id, actor, key, amount),
            )
            entity = cur.fetchone()[0]
            if with_event:
                cur.execute(
                    "INSERT INTO outbox (case_id, actor_id, service, event_type, "
                    "entity_id, amount) VALUES (%s,%s,%s,'Committed',%s,%s)",
                    (case_id, actor, service, entity, amount),
                )
        conn.commit()
    finally:
        conn.close()


def _project(case_id, total, events_applied):
    conn = psycopg2.connect(CRM_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO compensation_projection (case_id, total, "
                "events_applied) VALUES (%s,%s,%s) ON CONFLICT (case_id) DO UPDATE "
                "SET total = EXCLUDED.total, events_applied = EXCLUDED.events_applied",
                (case_id, total, events_applied),
            )
        conn.commit()
    finally:
        conn.close()


def test_clean_state_produces_no_findings(clean):
    report = reconcile("c1")
    assert report.findings == []
    assert report.clean


def test_unapplied_events_are_detected_as_lag(clean):
    _commit("billing", "c1", "A", "600.00", "k1")

    report = reconcile("c1")

    assert FindingType.PROJECTION_LAG in {f.type for f in report.findings}


def test_projection_drift_is_detected(clean):
    """The projection total disagreeing with the events it claims to have
    applied is a corruption a competent team would alert on."""
    _project("c1", Decimal("999.00"), events_applied=0)

    report = reconcile("c1")

    assert FindingType.PROJECTION_DRIFT in {f.type for f in report.findings}


def test_duplicate_idempotency_key_is_detected(clean):
    conn = psycopg2.connect(OWNER_DSNS["billing"])
    try:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE refunds DROP CONSTRAINT refunds_idempotency_key_key")
        conn.commit()
        _commit("billing", "c1", "A", "600.00", "dup", with_event=False)
        _commit("billing", "c1", "A", "600.00", "dup", with_event=False)

        report = reconcile("c1")
        assert FindingType.DUPLICATE_IDEMPOTENCY_KEY in {f.type for f in report.findings}
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM refunds")
            cur.execute("ALTER TABLE refunds ADD CONSTRAINT "
                        "refunds_idempotency_key_key UNIQUE (idempotency_key)")
        conn.commit()
        conn.close()


def test_reconciler_does_not_check_the_aggregate_ceiling(clean):
    """The load-bearing boundary.

    600 + 500 breaches a 1000 ceiling. The reconciler must NOT report it. That
    check is the solution under test; giving it to the baseline would assume the
    answer and make the silent-failure finding circular.
    """
    _commit("billing", "c1", "A", "600.00", "k1")
    _commit("ledger", "c1", "B", "500.00", "k2")

    report = reconcile("c1")
    types = {f.type for f in report.findings}

    assert not any("CEILING" in t.name or "INVARIANT" in t.name for t in types), (
        f"the reconciler reported {types} -- it must not know about the "
        "aggregate ceiling, or the silent-failure finding becomes circular"
    )


def test_a_fully_caught_up_breach_produces_no_findings_at_all(clean):
    """The finding, stated as a test.

    Both effects committed, both events applied, projection consistent. Ordinary
    monitoring sees a perfectly healthy system. The business state is wrong.
    """
    _commit("billing", "c1", "A", "600.00", "k1")
    _commit("ledger", "c1", "B", "500.00", "k2")

    conn = psycopg2.connect(CRM_DSN)
    try:
        with conn.cursor() as cur:
            for service, amount in (("billing", "600.00"), ("ledger", "500.00")):
                cur.execute(
                    "INSERT INTO applied_events (source_service, source_id, "
                    "case_id, amount) VALUES (%s, 1, 'c1', %s)",
                    (service, amount),
                )
        conn.commit()
    finally:
        conn.close()
    _project("c1", Decimal("1100.00"), events_applied=2)

    # Mark the source events applied so there is no lag either.
    for service in ("billing", "ledger"):
        conn = psycopg2.connect(OWNER_DSNS[service])
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE outbox SET applied_at = now()")
            conn.commit()
        finally:
            conn.close()

    report = reconcile("c1")

    assert report.clean, (
        f"expected ordinary monitoring to see nothing wrong, got {report.findings}"
    )
