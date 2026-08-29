"""Task 23: the clean slate is verified, never assumed.

Leftover rows push a sum over the ceiling regardless of concurrency, and the
resulting verdict is indistinguishable from a real violation. A reset that
silently half-worked would produce confident, wrong findings.

Asserted per table rather than by trusting TRUNCATE, because the failure being
guarded is precisely a reset that missed something.
"""

import psycopg2
import pytest

from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from apps.control.db import run_migrations as control_migrations
from apps.control.db import truncate_all as control_truncate
from apps.crm.db import run_migrations as crm_migrations
from apps.crm.db import truncate_all as crm_truncate
from apps.entitlements.db import run_migrations as ent_migrations
from apps.entitlements.db import truncate_all as ent_truncate
from apps.ledger.db import run_migrations as ledger_migrations
from apps.ledger.db import truncate_all as ledger_truncate
from oracle.quiescence import OWNER_DSNS

CONTROL_DSN = "postgresql://control:control@127.0.0.1:55435/control"
CRM_DSN = "postgresql://crm:crm@127.0.0.1:55436/crm"
ENT_DSN = "postgresql://entitlements:entitlements@127.0.0.1:55437/entitlements"

EXPECTED_EMPTY = {
    "billing": ["refunds", "decision_log", "request_log", "outbox", "plan_changes"],
    "ledger": ["credits", "decision_log", "request_log", "outbox"],
    "control": ["reservations", "request_log"],
    "crm": ["compensation_projection", "applied_events", "request_log"],
    "entitlements": ["feature_grants", "request_log"],
}


def _dsn(service):
    if service == "control":
        return CONTROL_DSN
    if service == "crm":
        return CRM_DSN
    if service == "entitlements":
        return ENT_DSN
    return OWNER_DSNS[service]


def _count(service, table):
    conn = psycopg2.connect(_dsn(service))
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {table}")
            return cur.fetchone()[0]
    finally:
        conn.close()


def _seed(service, table_sql):
    conn = psycopg2.connect(_dsn(service))
    try:
        with conn.cursor() as cur:
            cur.execute(table_sql)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def migrated():
    billing_migrations()
    ledger_migrations()
    control_migrations()
    crm_migrations()
    ent_migrations()


def test_every_table_is_empty_after_reset():
    _seed("billing", "INSERT INTO refunds (case_id, actor_id, idempotency_key, "
                     "amount, state) VALUES ('x','A','r-1','1.00','COMMITTED')")
    _seed("ledger", "INSERT INTO credits (case_id, actor_id, idempotency_key, "
                    "amount, state) VALUES ('x','B','c-1','1.00','COMMITTED')")
    _seed("control", "INSERT INTO reservations (case_id, actor_id, "
                     "idempotency_key, amount, state) "
                     "VALUES ('x','A','v-1','1.00','HELD')")
    _seed("crm", "INSERT INTO compensation_projection (case_id, total) "
                 "VALUES ('x','1.00')")
    _seed("entitlements", "INSERT INTO feature_grants (case_id, actor_id, "
                          "idempotency_key, feature, state) "
                          "VALUES ('x','A','f-1','sso','GRANTED')")

    billing_truncate()
    ledger_truncate()
    control_truncate()
    crm_truncate()
    ent_truncate()

    for service, tables in EXPECTED_EMPTY.items():
        for table in tables:
            assert _count(service, table) == 0, (
                f"{service}.{table} still has rows after reset -- leftover state "
                "is indistinguishable from a real violation"
            )


def test_reset_covers_every_table_that_exists():
    """Guards the real failure: a new table added and left out of the reset."""
    for service, expected in EXPECTED_EMPTY.items():
        conn = psycopg2.connect(_dsn(service))
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
                actual = {r[0] for r in cur.fetchall()}
        finally:
            conn.close()

        missed = actual - set(expected)
        assert not missed, (
            f"{service} has table(s) {missed} that the reset does not clear. "
            "Add them to truncate_all() or a future run will inherit their rows."
        )


def test_identity_sequences_restart_after_reset():
    """Ids restart, so a fingerprint comparison across replays is not defeated
    by ever-growing primary keys."""
    _seed("billing", "INSERT INTO refunds (case_id, actor_id, idempotency_key, "
                     "amount, state) VALUES ('x','A','r-9','1.00','COMMITTED')")
    billing_truncate()
    _seed("billing", "INSERT INTO refunds (case_id, actor_id, idempotency_key, "
                     "amount, state) VALUES ('y','A','r-10','1.00','COMMITTED')")

    conn = psycopg2.connect(_dsn("billing"))
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM refunds")
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()
    billing_truncate()
