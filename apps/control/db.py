"""Control service database."""

from __future__ import annotations

import pathlib

from libs.service_common import connect as _connect

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
DSN_ENV = "CONTROL_DSN"
DEFAULT_DSN = "postgresql://control:control@127.0.0.1:55435/control"


def connect():
    return _connect(DSN_ENV, DEFAULT_DSN)


def run_migrations() -> None:
    sql = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()


def truncate_all() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE reservations, request_log RESTART IDENTITY")
        conn.commit()
