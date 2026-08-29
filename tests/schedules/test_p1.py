"""P1 -- sequential negative control. MUST PASS.

A completes its refund entirely before B begins, so B observes A's committed 600
and correctly decides its 300 still fits under the 1000 ceiling.

This is what proves the oracle is not trigger-happy. If P1 reports a violation,
the instrument is wrong, not the system -- and every other verdict is worthless
until that is fixed.

It must also fail closed if it passes while any waiter is still parked.
Otherwise "pass" could mean the second actor never ran at all, which looks
identical to a clean run.
"""

from decimal import Decimal

from oracle.invariants import Verdict
from schedules.runner import assert_actors_succeeded, run_schedule


def test_p1_sequential_is_clean(clean_state):
    outcome = run_schedule("P1", clean_state)
    assert_actors_succeeded(outcome)

    assert outcome.result.verdict is Verdict.CLEAN
    assert outcome.result.committed_total == Decimal("900.00")


def test_p1_leaves_no_waiter_parked(clean_state):
    """A pass with a parked waiter means an actor never ran."""
    outcome = run_schedule("P1", clean_state)

    assert outcome.parked_waiters == [], (
        f"P1 reported clean while {outcome.parked_waiters} were still parked -- "
        "an actor may never have run"
    )


def test_p1_released_every_declared_step(clean_state):
    """Every checkpoint in the schedule was actually reached and released."""
    outcome = run_schedule("P1", clean_state)

    assert outcome.release_order == [
        ["A", "billing.after_read_before_decide", 0],
        ["A", "billing.after_commit_before_ack", 0],
        ["B", "ledger.after_read_before_decide", 0],
        ["B", "ledger.after_commit_before_ack", 0],
    ]


def test_p1_api_view_agrees_with_database_truth(clean_state):
    """With no concurrency there is nothing for the API to be stale about."""
    outcome = run_schedule("P1", clean_state)

    assert outcome.divergence["diverged"] is False
