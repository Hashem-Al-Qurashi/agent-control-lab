"""Transactional outbox.

Events are written in the SAME transaction as the effect they describe. If the
two could commit separately, propagation lag would be a bug in the harness
rather than a property of the architecture -- and the whole point of Stage 1 is
that the lag is real and honest.

The outbox is per-service, in that service's own database, because there is no
shared transaction boundary to put it anywhere else. That constraint is the
premise of the experiment, not an inconvenience.

Lag is measurable via pending_count(). An unmeasurable lag cannot be reported as
a condition of a result.
"""

from __future__ import annotations

from decimal import Decimal


def publish(cur, *, case_id: str, actor_id: str, service: str,
            event_type: str, entity_id: int, amount: Decimal) -> None:
    """Append an event using the CALLER'S cursor, so it shares their transaction.

    Taking a cursor rather than opening a connection is the whole design. A
    function that opened its own connection could commit the event while the
    effect rolled back.
    """
    cur.execute(
        "INSERT INTO outbox (case_id, actor_id, service, event_type, entity_id, "
        "amount) VALUES (%s, %s, %s, %s, %s, %s)",
        (case_id, actor_id, service, event_type, entity_id, amount),
    )


def claim_unapplied(connect, limit: int = 100) -> list[dict]:
    """Unapplied events in publication order.

    Ordered by id, which is the order they committed. A projection that applied
    them out of order would produce a state no schedule described.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, case_id, actor_id, service, event_type, entity_id, amount "
            "FROM outbox WHERE applied_at IS NULL ORDER BY id LIMIT %s",
            (limit,),
        )
        return [
            {
                "id": r[0], "case_id": r[1], "actor_id": r[2], "service": r[3],
                "event_type": r[4], "entity_id": r[5], "amount": r[6],
            }
            for r in cur.fetchall()
        ]


def mark_applied(connect, event_ids: list[int]) -> None:
    if not event_ids:
        return
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE outbox SET applied_at = now() WHERE id = ANY(%s)",
            (event_ids,),
        )
        conn.commit()


def pending_count(connect) -> int:
    """How far behind the projection is. This is the lag, made observable."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM outbox WHERE applied_at IS NULL")
        return cur.fetchone()[0]
