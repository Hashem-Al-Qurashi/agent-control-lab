"""S6 -- authorization prevents the action.

The anti-strawman control for the authorization layer. Everywhere else,
authorization permits the action and the aggregate still breaks, which invites
the reading that authorization here is decorative.

Both actors request above the single-action threshold without approval
authority. Both are refused. Nothing is written.

Per-action authorization demonstrably works -- which is exactly why S1 matters:
authorization working is not the same as the aggregate being correct. S6 is what
makes that a comparison rather than an excuse.
"""

from decimal import Decimal

import psycopg2

from oracle.invariants import Verdict
from oracle.quiescence import OWNER_DSNS
from schedules.runner import run_schedule


def test_s6_writes_nothing(clean_state):
    outcome = run_schedule("S6", clean_state)

    assert outcome.result.verdict is Verdict.CLEAN
    assert outcome.result.committed_total == Decimal("0.00")


def test_s6_publishes_no_events(clean_state):
    """A refused action must not be half-done anywhere."""
    run_schedule("S6", clean_state)

    for service in ("billing", "ledger"):
        conn = psycopg2.connect(OWNER_DSNS[service])
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM outbox WHERE case_id = %s",
                            ("case-s6",))
                assert cur.fetchone()[0] == 0, f"{service} published an event"
        finally:
            conn.close()


def test_s6_both_actors_attempted_and_both_were_refused(clean_state):
    """A denial must surface, and BOTH actors must actually have tried.

    An earlier version of this schedule declared service checkpoints that a
    denied action never reaches. The pointer waited on a step that could not
    arrive, B parked until the barrier timed out without attempting anything,
    and the "no events published" assertion passed vacuously.
    """
    outcome = run_schedule("S6", clean_state)

    errors = [o for o in outcome.actor_outcomes if o[0] == "error"]
    assert {o[1] for o in errors} == {"A", "B"}, (
        f"both actors must have attempted and been refused, got {outcome.actor_outcomes}"
    )
    assert all("403" in str(o[2]) for o in errors)
    assert outcome.parked_waiters == [], "a waiter was stranded"


def test_s6_proves_authorization_is_not_decorative(clean_state):
    """Stated as its own assertion because it is the point of the schedule."""
    s6 = run_schedule("S6", clean_state)
    assert s6.result.committed_total == Decimal("0.00")

    # The same amounts, with approval authority, are permitted elsewhere --
    # so the refusal is about authority, not about the amount being impossible.
    from schedules.runner import load

    assert all(
        a.get("scopes") and "refund:approved" not in a.get("scopes", [])
        and "credit:approved" not in a.get("scopes", [])
        for a in load("S6")["actors"]
    )
