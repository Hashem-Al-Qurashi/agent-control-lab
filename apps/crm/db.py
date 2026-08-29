"""CRM's own database. Holds a projection, never an authoritative record."""

from __future__ import annotations

import pathlib

from libs.service_common import connect as _connect

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
DSN_ENV = "CRM_DSN"
DEFAULT_DSN = "postgresql://crm:crm@127.0.0.1:55436/crm"


def connect():
    return _connect(DSN_ENV, DEFAULT_DSN)


def run_migrations() -> None:
    sql = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()


def truncate_all() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE compensation_projection, applied_events, request_log "
            "RESTART IDENTITY"
        )
        conn.commit()
