"""Quiescence gate.

Two independent Postgres admit no cross-database consistent snapshot. Reading
while actors are still in flight yields a torn state: an in-flight transfer is
double-counted (false violation) or missed (masked violation). Neither is
adjudicable after the fact, so the oracle refuses to evaluate rather than
producing a number whose meaning cannot be defended.
"""

from __future__ import annotations

import psycopg2

from oracle.sql import DSNS, READONLY_PASSWORD, READONLY_USER

OWNER_DSNS = {
    "billing": "postgresql://billing:billing@127.0.0.1:55433/billing",
    "ledger": "postgresql://ledger:ledger@127.0.0.1:55434/ledger",
}


class NotQuiescent(Exception):
    """Evaluation was attempted while the system was still moving."""


def ensure_quiescent(parked_waiters: list) -> None:
    if parked_waiters:
        raise NotQuiescent(
            f"{len(parked_waiters)} waiter(s) still parked at the barrier: "
            f"{parked_waiters}. Evaluating now would read a torn cross-database "
            "state whose verdict cannot be reproduced."
        )


def grant_readonly() -> None:
    """Create the oracle's read-only role in both databases.

    Idempotent so it can run before any evaluation.
    """
    for service, dsn in OWNER_DSNS.items():
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s", (READONLY_USER,)
                )
                if cur.fetchone() is None:
                    cur.execute(
                        f"CREATE ROLE {READONLY_USER} LOGIN PASSWORD "
                        f"'{READONLY_PASSWORD}'"
                    )
                cur.execute(f"GRANT CONNECT ON DATABASE {service} TO {READONLY_USER}")
                cur.execute(f"GRANT USAGE ON SCHEMA public TO {READONLY_USER}")
                cur.execute(
                    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO "
                    f"{READONLY_USER}"
                )
                cur.execute(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON "
                    f"TABLES TO {READONLY_USER}"
                )
                # Explicitly withhold write. Defence in depth against a future
                # migration granting more than intended.
                cur.execute(
                    "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN "
                    f"SCHEMA public FROM {READONLY_USER}"
                )
        finally:
            conn.close()
