"""Run manifest: the rig's own account of the conditions a result was produced under.

A number without its conditions is not evidence. The manifest records the facts
that determine whether a verdict means anything:

  * that the two services really did use separate databases
  * the isolation level each database was running at
  * whether the driver retries on serialization failure

The last two matter because SERIALIZABLE with driver-level retry silently aborts
and replays one transaction, handing you a lock you never scripted. The race
then never opens, P2 passes, and the honest-looking conclusion -- "the thesis is
false" -- is wrong.
"""

from __future__ import annotations

import subprocess
from urllib.parse import urlparse

import psycopg2

from apps.billing.db import DEFAULT_DSN as BILLING_DEFAULT
from apps.ledger.db import DEFAULT_DSN as LEDGER_DEFAULT


def dsn_parts(dsn: str) -> dict[str, str | int | None]:
    parsed = urlparse(dsn)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "dbname": (parsed.path or "/").lstrip("/"),
        "user": parsed.username,
    }


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # pragma: no cover - manifest must never break a run
        return "unknown"


def _database_facts(dsn: str) -> dict:
    parts = dsn_parts(dsn)
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SHOW transaction_isolation")
        isolation = cur.fetchone()[0]
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
    return {
        **parts,
        "isolation_level": isolation,
        "server_version": version,
        # psycopg2 does not retry on serialization failure; it raises
        # SerializationFailure and leaves the decision to the caller. Recorded
        # explicitly rather than assumed, because a driver that DID retry would
        # silently close the race window this experiment depends on.
        "driver": "psycopg2",
        "driver_retries_on_serialization_failure": False,
    }


def build_manifest(
    billing_dsn: str = BILLING_DEFAULT, ledger_dsn: str = LEDGER_DEFAULT
) -> dict:
    billing = _database_facts(billing_dsn)
    ledger = _database_facts(ledger_dsn)

    topology_error = None
    if billing["dbname"] == ledger["dbname"] and (billing["host"], billing["port"]) == (
        ledger["host"],
        ledger["port"],
    ):
        topology_error = (
            "billing and ledger share the same database -- there is a common "
            "transaction boundary, so the premise of the experiment is false"
        )

    return {
        "git_sha": _git_sha(),
        "topology_valid": topology_error is None,
        "topology_error": topology_error,
        "databases": {"billing": billing, "ledger": ledger},
    }
