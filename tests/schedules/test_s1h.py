"""S1H -- coordination fixes staleness, not just concurrency.

S1's failure is different in kind from P2's. P2 was a timing race: both actors
read before either wrote. S1 is not a race -- B reads strictly after A has fully
committed and is wrong anyway, because the view it was given had not caught up.

P0 showed a reservation fixes the race. Whether the same primitive fixes
staleness is a separate question, and this answers it.

The reason it works is the interesting part: the control service holds
AUTHORITATIVE reservation state, not a derived view. B's projection is exactly
as stale as in S1. What changed is that B must ask an authority that cannot be
behind.

So the remedy is not "make the projection faster" -- a faster projection is
still a projection. It is having an authority for the aggregate at all.
"""

from decimal import Decimal

from oracle.invariants import Verdict
from schedules.runner import assert_actors_succeeded, run_schedule

CRM_DSN = "postgresql://crm:crm@127.0.0.1:55436/crm"


def test_s1h_is_clean(clean_state):
    outcome = run_schedule("S1H", clean_state)
    assert_actors_succeeded(outcome)

    assert outcome.result.verdict is Verdict.CLEAN, (
        "the reservation failed to prevent the stale-read breach -- if this "
        "violates, coordination does not generalise from races to staleness"
    )
    assert outcome.result.committed_total == Decimal("600.00")


def test_s1h_projection_was_just_as_stale_as_in_s1(clean_state):
    """The load-bearing comparison.

    If B had seen a current projection this would prove nothing -- it would be
    S1C with extra steps. B's view must be stale AND the outcome still correct.
    """
    outcome = run_schedule("S1H", clean_state)
    order = [tuple(r) for r in outcome.release_order]

    b_read = min(i for i, r in enumerate(order) if r[0] == "B")
    applies_before_b = sum(
        1 for r in order[:b_read] if r[1] == "crm.before_apply_event"
    )

    assert applies_before_b == 0, (
        f"{applies_before_b} event(s) were applied before B read -- B's view was "
        "not stale, so this does not test what S1 tests"
    )


def test_s1h_and_s1_differ_only_in_the_available_authority(clean_state):
    """Same scenario, same staleness. One has an authority for the aggregate."""
    from schedules.runner import load

    s1, s1h = load("S1"), load("S1H")

    assert s1["authorized_compensation"] == s1h["authorized_compensation"]
    amounts = lambda spec: [
        a["amount"] for a in spec["actors"] if a["action"] != "project"
    ]
    assert amounts(s1) == amounts(s1h)
    assert s1.get("use_reservations") is None
    assert s1h["use_reservations"] is True


def test_s1h_second_actor_declined_rather_than_erroring(clean_state):
    """A refusal is a correct outcome, not a crash."""
    outcome = run_schedule("S1H", clean_state)

    assert all(o[0] == "ok" for o in outcome.actor_outcomes), outcome.actor_outcomes


def test_s1h_leaves_no_waiter_parked(clean_state):
    outcome = run_schedule("S1H", clean_state)
    assert outcome.parked_waiters == []
