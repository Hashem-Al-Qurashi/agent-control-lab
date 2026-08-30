"""The decision log for a case, read as part of the run that produced it.

ADR-007 spent its life suspecting the scheduler. The captured diff showed the
barrier's release order identical across 500 replays under hostile concurrent
load; the only field that ever differed was the decision log, and it differed by
being EMPTY -- because another process truncated the table between the run
finishing and the fingerprint reading it.

The divergence was the measurement reading mutable state that was not part of
the run it described. So the read moves inside the run, next to the oracle's own
evaluation, where the quiescence gate already establishes that nothing is in
flight.
"""

from __future__ import annotations

import psycopg2

from oracle.quiescence import OWNER_DSNS

SOURCES = ("billing", "ledger")


def transitions(case_id: str) -> list[tuple]:
    """Every recorded state transition for a case, in a total order.

    Sorted across the two independent databases: each assigns its own sequence,
    so their union has no inherent order and comparing unsorted lists would
    report a divergence whenever two rows happened to interleave differently.
    """
    rows: list[tuple] = []
    for service in SOURCES:
        conn = psycopg2.connect(OWNER_DSNS[service])
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sequence, actor_id, service, from_state, to_state, "
                    "amount FROM decision_log WHERE case_id = %s ORDER BY sequence",
                    (case_id,),
                )
                rows.extend(cur.fetchall())
        finally:
            conn.close()
    return sorted(tuple(str(v) for v in row) for row in rows)
