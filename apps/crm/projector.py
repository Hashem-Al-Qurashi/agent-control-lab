"""Folds service events into CRM's compensation projection.

Where the checkpoint sits is the whole design. The schedule does not control
transport -- the consumer may fetch whenever it likes. What it controls is the
moment an event is APPLIED, because that is when CRM becomes allowed to observe
the effect. A checkpoint after the apply would order nothing an agent could see.

Re-delivery is guarded by (source_service, source_id) rather than by assuming
exactly-once delivery. Event ids are only unique within a service, so keying on
the id alone would silently drop one of two concurrent events. A double-counted
event would fabricate a violation out of nothing -- the worst available failure,
because it has the shape of the result being claimed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable

from apps.crm.db import connect


def _no_checkpoint(name: str) -> None:
    """Default: the projector takes no part in any schedule."""


def projection_total(case_id: str) -> Decimal:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT total FROM compensation_projection WHERE case_id = %s",
            (case_id,),
        )
        row = cur.fetchone()
        return Decimal(row[0]) if row else Decimal("0")


def projection_lag(case_id: str, authoritative_total: Decimal) -> Decimal:
    """How far behind reality the projection currently is.

    Reported alongside any verdict. A stale read is only meaningful if the
    staleness is quantified.
    """
    return authoritative_total - projection_total(case_id)


def _already_applied(cur, service: str, source_id: int) -> bool:
    cur.execute(
        "SELECT 1 FROM applied_events WHERE source_service = %s AND source_id = %s",
        (service, source_id),
    )
    return cur.fetchone() is not None


def apply_pending(
    sources: dict, checkpoint: Callable[[str], None] = _no_checkpoint
) -> int:
    """Apply every unapplied event from each source, in publication order.

    Returns the number applied.
    """
    # Before polling anything. Without this the schedule cannot say WHEN the
    # projector looks, so whether it finds events at all depends on how long its
    # imports happened to take. That is a race dressed as a result: on a slower
    # machine the projector polls late and the schedule works; on a faster one it
    # polls early, finds nothing, exits, and the declared checkpoints never fire.
    checkpoint("crm.before_poll")

    applied = 0
    for service, source in sources.items():
        for event in source.unapplied():
            # Fired while the projection is still stale. This is the moment the
            # schedule can hold, and holding it is what makes staleness
            # observable to an agent reading CRM.
            checkpoint("crm.before_apply_event")

            with connect() as conn, conn.cursor() as cur:
                if _already_applied(cur, service, event["id"]):
                    conn.commit()
                    source.mark_applied(event["id"])
                    continue

                amount = Decimal(str(event["amount"]))
                cur.execute(
                    "INSERT INTO applied_events "
                    "(source_service, source_id, case_id, amount) "
                    "VALUES (%s, %s, %s, %s)",
                    (service, event["id"], event["case_id"], amount),
                )
                cur.execute(
                    "INSERT INTO compensation_projection "
                    "(case_id, total, events_applied) VALUES (%s, %s, 1) "
                    "ON CONFLICT (case_id) DO UPDATE SET "
                    "total = compensation_projection.total + EXCLUDED.total, "
                    "events_applied = compensation_projection.events_applied + 1, "
                    "updated_at = now()",
                    (event["case_id"], amount),
                )
                conn.commit()

            # Marked at the source only after the projection has committed. The
            # reverse order could lose an event permanently.
            source.mark_applied(event["id"])
            applied += 1
    return applied
