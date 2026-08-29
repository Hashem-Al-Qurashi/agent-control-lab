"""S4 -- apply order does not change the total. S5 -- redelivery does not inflate it.

Both are controls, and both exist to close off readings of S1 that would make it
an artefact rather than a result.

S4: if apply ORDER mattered, "the projection was behind" would be an incomplete
explanation of S1.

S5: if redelivery double-counted, the projection could fabricate a violation out
of nothing -- with the exact shape of the real result. If S5 fails, no S-series
verdict can be trusted.
"""

from decimal import Decimal

import psycopg2

from oracle.invariants import Verdict
from schedules.runner import assert_actors_succeeded, run_schedule

CRM_DSN = "postgresql://crm:crm@127.0.0.1:55436/crm"


def _projection(case_id):
    conn = psycopg2.connect(CRM_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT total, events_applied FROM compensation_projection "
                "WHERE case_id = %s",
                (case_id,),
            )
            row = cur.fetchone()
            return (Decimal(row[0]), row[1]) if row else (Decimal("0"), 0)
    finally:
        conn.close()


def test_s4_reversed_apply_order_reaches_the_same_state(clean_state):
    outcome = run_schedule("S4", clean_state)
    assert_actors_succeeded(outcome)

    assert outcome.result.verdict is Verdict.CLEAN
    assert outcome.result.committed_total == Decimal("600.00")


def test_s4_b_declined_because_it_saw_the_correct_total(clean_state):
    """Not because something went wrong -- because the view was current."""
    run_schedule("S4", clean_state)

    total, _ = _projection("case-s4")
    assert total == Decimal("600.00")


def test_s5_redelivery_does_not_move_the_projection(clean_state):
    """The load-bearing control for the projection itself."""
    outcome = run_schedule("S5", clean_state)
    assert_actors_succeeded(outcome)

    total, applied = _projection("case-s5")
    assert total == Decimal("600.00"), (
        f"projection moved to {total} after redelivery -- it double-counted, and "
        "a double count fabricates a violation with the shape of the real result"
    )
    assert applied == 1, f"{applied} applications recorded for one event"


def test_s5_stays_clean(clean_state):
    outcome = run_schedule("S5", clean_state)
    assert outcome.result.verdict is Verdict.CLEAN
    assert outcome.result.committed_total == Decimal("600.00")


def test_s4_and_s5_leave_no_waiter_parked(clean_state):
    for schedule in ("S4", "S5"):
        outcome = run_schedule(schedule, clean_state)
        assert outcome.parked_waiters == [], f"{schedule} stranded a waiter"
