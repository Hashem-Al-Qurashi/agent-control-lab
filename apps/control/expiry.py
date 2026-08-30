"""Reclaim budget from holds whose agents never came back.

Called inside the reservation lock rather than only from a background loop, so
the budget a dead agent was holding is already free at the moment a live agent
contends for it. A purely background reaper would leave a window whose length is
the reaper's interval, and that window is indistinguishable from the control
correctly refusing.
"""

from __future__ import annotations

from libs.clock import Clock


def expire_due(cur, clock: Clock) -> int:
    """Mark every overdue HELD reservation EXPIRED. Returns how many.

    Only HELD rows are touched. Reaping a COMMITTED hold would free budget that
    was genuinely spent and authorise the next agent to overspend -- the control
    causing the exact breach it exists to prevent.

    A NULL deadline is never due -- absence of a deadline is not a deadline in
    the past.

    The `expires_at IS NOT NULL` clause is deliberately redundant: SQL's
    three-valued logic already excludes those rows, because `NULL <= ts` is NULL
    rather than TRUE. Verified by mutation -- removing the clause changes no
    test. It stays as a statement of intent, so a reader does not have to
    re-derive NULL comparison semantics to know that pre-migration holds are
    safe. It is not what makes them safe.
    """
    cur.execute(
        "UPDATE reservations SET state = 'EXPIRED' "
        "WHERE state = 'HELD' "
        "  AND expires_at IS NOT NULL "
        "  AND expires_at <= %s "
        "RETURNING id",
        (clock.now(),),
    )
    return len(cur.fetchall())
