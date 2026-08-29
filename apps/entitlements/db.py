"""Entitlements' own database. Owns grants, never the plan."""

from __future__ import annotations

import pathlib

from libs.service_common import connect as _connect

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
DSN_ENV = "ENTITLEMENTS_DSN"
DEFAULT_DSN = "postgresql://entitlements:entitlements@127.0.0.1:55437/entitlements"


def connect():
    return _connect(DSN_ENV, DEFAULT_DSN)


def run_migrations() -> None:
    sql = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()


def truncate_all() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE feature_grants, request_log RESTART IDENTITY")
        conn.commit()
