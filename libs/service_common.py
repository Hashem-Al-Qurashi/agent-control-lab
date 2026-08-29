"""Infrastructure shared by Billing and Ledger.

Only genuinely identical mechanism lives here -- barrier participation, decision
log sequencing, database connection. The domain stays separate: the two services
own different entities in different databases, and sharing that would undermine
the premise that no single transaction boundary spans them.

The split matters. Sharing *infrastructure* removes divergence risk; sharing
*domain* would quietly couple the two systems the experiment needs independent.
"""

from __future__ import annotations

import os

import psycopg2

from libs.barrier.client import BarrierClient


def barrier_client() -> BarrierClient | None:
    """Read configuration at call time, never at import.

    Import-time reads bake configuration into the module and break the
    process-pool model, where one pre-warmed interpreter serves many cases.
    """
    if os.environ.get("BARRIER_ENABLED", "0") != "1":
        return None
    url = os.environ.get("BARRIER_URL")
    if not url:
        raise RuntimeError("BARRIER_ENABLED=1 but BARRIER_URL is unset")
    return BarrierClient(url)


def checkpoint(name: str) -> None:
    """Participate in the schedule, or don't -- but never silently half-do it.

    Disabling is explicit configuration. A checkpoint that no-ops because it
    could not reach the coordinator would fail open, and the whole barrier design
    is fail-closed.
    """
    barrier = barrier_client()
    if barrier is None:
        return
    try:
        barrier.checkpoint(name)
    finally:
        barrier.close()


def connect(env_var: str, default_dsn: str):
    conn = psycopg2.connect(os.environ.get(env_var, default_dsn))
    conn.autocommit = False
    return conn


def next_sequence(cur, case_id: str) -> int:
    """Per-case monotonic sequence from a single issuing authority.

    Scoped to the case rather than global so the two services can each append
    without a shared counter, while the oracle can still replay a total order
    per case.
    """
    cur.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM decision_log WHERE case_id = %s",
        (case_id,),
    )
    return cur.fetchone()[0]


def append_decision(
    cur,
    *,
    case_id: str,
    actor_id: str,
    service: str,
    entity_id: int,
    from_state: str | None,
    to_state: str,
    amount,
) -> None:
    """Append-only transition record.

    Written even though Stage 0's oracle reads SQL at a quiescence gate: later
    modes have no quiescence point, and history cannot be reconstructed from
    mutable rows, so this cannot be retrofitted.
    """
    cur.execute(
        "INSERT INTO decision_log "
        "(case_id, sequence, actor_id, service, entity_id, from_state, "
        " to_state, amount) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            case_id,
            next_sequence(cur, case_id),
            actor_id,
            service,
            entity_id,
            from_state,
            to_state,
            amount,
        ),
    )
