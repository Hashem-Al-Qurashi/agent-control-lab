"""Ledger's own database. Raw SQL, no ORM.

Connection details are read at call time, never at import.
"""

from __future__ import annotations

import pathlib

from libs.service_common import connect as _connect

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
DSN_ENV = "LEDGER_DSN"
DEFAULT_DSN = "postgresql://ledger:ledger@127.0.0.1:55434/ledger"


def connect():
    return _connect(DSN_ENV, DEFAULT_DSN)


def run_migrations() -> None:
    sql = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()


def truncate_all() -> None:
    """Verified clean slate. Leftover rows push a sum over the ceiling
    regardless of concurrency, which is indistinguishable from a real
    violation."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE credits, decision_log, request_log RESTART IDENTITY")
        conn.commit()
