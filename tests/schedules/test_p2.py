"""P2 -- concurrent read-check-write race. MUST produce a violation.

Both actors observe zero, both decide correctly from what they observed, and the
aggregate breaches the ceiling. Every individual action is authorised,
idempotent, locally valid and successfully executed.

A POSITIVE CONTROL, not a discovery. Read-then-write across two uncoordinated
systems is textbook and Stage 0 claims nothing from it. Its job is to prove the
rig can deterministically produce a known violation.

If P2 does not violate, the rig is broken. Check in order: barrier placement
relative to commit, actor scoping, server worker count, oracle correctness, DB
isolation level. Draw no conclusion about the thesis.
"""

from decimal import Decimal

from oracle.invariants import Verdict
from schedules.runner import assert_actors_succeeded, run_schedule


def test_p2_produces_a_violation(clean_state):
    outcome = run_schedule("P2", clean_state)
    assert_actors_succeeded(outcome)

    assert outcome.result.verdict is Verdict.VIOLATION, (
        "P2 did not violate -- the rig is broken, not the thesis. Check barrier "
        "placement relative to commit, actor scoping, worker count, the oracle, "
        "and the DB isolation level."
    )


def test_p2_overage_is_exactly_one_hundred(clean_state):
    """An exact figure, not merely 'a violation'. A different number means the
    schedule executed differently from the one declared."""
    outcome = run_schedule("P2", clean_state)

    assert outcome.result.committed_total == Decimal("1100.00")
    assert outcome.result.realized_overage == Decimal("100.00")


def test_p2_is_a_violation_not_inconclusive(clean_state):
    """Distinct idempotency keys from distinct actors: two genuine decisions,
    not one decision recorded twice."""
    outcome = run_schedule("P2", clean_state)

    assert outcome.result.verdict is not Verdict.INCONCLUSIVE
    assert outcome.result.reason is None


def test_p2_both_actors_succeeded(clean_state):
    """Neither actor errored. A crashed actor would make the run meaningless."""
    outcome = run_schedule("P2", clean_state)

    assert all(o[0] == "ok" for o in outcome.actor_outcomes), outcome.actor_outcomes


def test_p2_executed_the_declared_interleaving(clean_state):
    """The violation must come from the schedule that was declared, not from
    some other ordering that happened to occur."""
    outcome = run_schedule("P2", clean_state)

    assert outcome.release_order == [
        ["A", "agent.before_reads", 0],
        ["B", "agent.before_reads", 0],
        ["B", "agent.after_reads_before_act", 0],
        ["A", "agent.after_reads_before_act", 0],
        ["A", "billing.after_read_before_decide", 0],
        ["A", "billing.after_commit_before_ack", 0],
        ["B", "ledger.after_read_before_decide", 0],
        ["B", "ledger.after_commit_before_ack", 0],
    ]


def test_p2_leaves_no_waiter_parked(clean_state):
    outcome = run_schedule("P2", clean_state)
    assert outcome.parked_waiters == []
