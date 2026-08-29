"""Ledger's own database. Raw SQL, no ORM.

Connection details are read at call time, never at import. An import-time read
would bake configuration into the module and break the process-pool model, where
one pre-warmed interpreter serves many cases.
"""

from __future__ import annotations

import os
import pathlib

import psycopg2

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"

DEFAULT_DSN = "postgresql://ledger:ledger@127.0.0.1:55434/ledger"


def dsn() -> str:
    return os.environ.get("LEDGER_DSN", DEFAULT_DSN)


def connect():
    conn = psycopg2.connect(dsn())
    conn.autocommit = False
    return conn


def run_migrations() -> None:
    sql = "\n".join(
        p.read_text() for p in sorted(MIGRATIONS.glob("*.sql"))
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()


def truncate_all() -> None:
    """Verified clean slate. Leftover rows push a sum over the ceiling
    regardless of concurrency, which would be indistinguishable from a real
    violation."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE credits, decision_log RESTART IDENTITY")
        conn.commit()
