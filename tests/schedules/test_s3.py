"""S3 -- partial catch-up still breaks the invariant.

S1 showed a fully-lagged projection breaks it. S1C showed a fully caught-up one
does not. S3 answers the question between them, and rules out a comfortable
reading of S1: that the problem only arises when the view is completely cold.

It is not all-or-nothing. The exposure tracks how far behind the view is, and a
partially-current view is still a wrong view.
"""

from decimal import Decimal

from oracle.invariants import Verdict
from schedules.runner import assert_actors_succeeded, run_schedule


def test_s3_violates_despite_partial_catch_up(clean_state):
    outcome = run_schedule("S3", clean_state)
    assert_actors_succeeded(outcome)

    assert outcome.result.verdict is Verdict.VIOLATION
    assert outcome.result.committed_total == Decimal("1100.00")
    assert outcome.result.realized_overage == Decimal("100.00")


def test_s3_third_actor_saw_a_partially_current_view(clean_state):
    """The distinguishing property: C's view was neither cold nor correct.

    If C had seen 0 this would be S1 with extra actors. If it had seen 700 it
    would have declined. Seeing exactly 400 is what makes S3 its own case.
    """
    outcome = run_schedule("S3", clean_state)

    applies_before_c = 0
    for actor, checkpoint, _ in (tuple(r) for r in outcome.release_order):
        if actor == "C":
            break
        if checkpoint == "crm.before_apply_event":
            applies_before_c += 1

    assert applies_before_c == 1, (
        f"{applies_before_c} events were applied before C read -- S3 requires "
        "exactly one, or it is not testing partial catch-up"
    )


def test_s3_every_action_was_individually_within_authority(clean_state):
    """No action needed approval authority. Per-action authorization holds
    throughout, and the aggregate still breaks."""
    from schedules.runner import load

    for actor in load("S3")["actors"]:
        if actor["action"] == "project":
            continue
        assert Decimal(actor["amount"]) <= Decimal("500.00")


def test_s3_leaves_no_waiter_parked(clean_state):
    outcome = run_schedule("S3", clean_state)
    assert outcome.parked_waiters == []
