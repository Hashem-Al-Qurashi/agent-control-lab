"""The oracle's own SQL and its own read-only connections.

Deliberately duplicates knowledge of the schema rather than importing the
services' modules. If the oracle shared filters or models with the system under
test, a bug in those would appear in both the system and its judge and cancel
out invisibly -- the one failure mode a judge must not have.

Read-only credentials, so the oracle cannot perturb what it measures.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from decimal import Decimal

import psycopg2

READONLY_USER = "oracle_ro"
READONLY_PASSWORD = "oracle_ro"

DSNS = {
    "billing": ("BILLING_RO_DSN",
                f"postgresql://{READONLY_USER}:{READONLY_PASSWORD}"
                "@127.0.0.1:55433/billing"),
    "ledger": ("LEDGER_RO_DSN",
               f"postgresql://{READONLY_USER}:{READONLY_PASSWORD}"
               "@127.0.0.1:55434/ledger"),
}

TABLES = {"billing": "refunds", "ledger": "credits"}

# COMMITTED and not VOIDED is the verdict. SETTLED counts: it differs from
# COMMITTED only in irreversibility, not in whether the money is committed.
VERDICT_STATES = ("COMMITTED", "SETTLED")
# Reported alongside, never the verdict.
OBLIGATED_STATES = ("PENDING", "COMMITTED", "SETTLED")


@contextmanager
def readonly_connection(service: str):
    env, default = DSNS[service]
    conn = psycopg2.connect(os.environ.get(env, default))
    try:
        yield conn
    finally:
        conn.close()


def _sum(service: str, case_id: str, states: tuple[str, ...]) -> Decimal:
    # Table name comes from the TABLES constant above, never from a request.
    # Postgres cannot bind an identifier as a parameter, so interpolation is
    # required here; every user-controlled value below is bound with %s.
    table = TABLES[service]
    with readonly_connection(service) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(SUM(amount), 0) FROM {table} "
            "WHERE case_id = %s AND state = ANY(%s)",
            (case_id, list(states)),
        )
        return Decimal(cur.fetchone()[0])


def committed_total(case_id: str) -> Decimal:
    return sum(
        (_sum(s, case_id, VERDICT_STATES) for s in TABLES), start=Decimal("0")
    )


def obligated_total(case_id: str) -> Decimal:
    return sum(
        (_sum(s, case_id, OBLIGATED_STATES) for s in TABLES), start=Decimal("0")
    )


def settled_total(case_id: str) -> Decimal:
    return sum((_sum(s, case_id, ("SETTLED",)) for s in TABLES), start=Decimal("0"))


def rows_by_idempotency_key(case_id: str) -> dict[str, list[tuple]]:
    """Grouped so a duplicated key can be told apart from two distinct actions."""
    grouped: dict[str, list[tuple]] = {}
    for service, table in TABLES.items():
        with readonly_connection(service) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT idempotency_key, actor_id, amount, state FROM {table} "
                "WHERE case_id = %s",
                (case_id,),
            )
            for key, actor, amount, state in cur.fetchall():
                grouped.setdefault(key, []).append((service, actor, amount, state))
    return grouped
