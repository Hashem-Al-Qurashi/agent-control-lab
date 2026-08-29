"""S1 -- the Stage 1 thesis, and S1C, its control.

S1 is the case Stage 0 could not reach. In P2 the actors overlapped, and P1
showed that sequencing them fixes it. In S1 they do not overlap at all: A
completes entirely, including acknowledgement, before B begins reading.

Sequencing is supposed to be the fix. It is not, because B does not read the
authoritative store -- it reads the CRM projection, which is the integration
point it was given, and that projection has not applied A's event yet.

S1C is identical except for WHEN the projection catches up. That pair isolates a
single variable: not the agent, not the ordering, not the amounts, only whether
the read model had caught up when the agent consulted it.

Without S1C, "you gave the agent stale data and it acted on stale data" is a
tautology rather than a result -- the same role P0 plays for P2.
"""

from decimal import Decimal

from oracle.invariants import Verdict
from schedules.runner import (
    assert_actors_succeeded,
    assert_schedule_executed,
    expected_release_order,
    run_schedule,
)


def test_s1_violates_even_though_the_actors_never_overlap(clean_state):
    outcome = run_schedule("S1", clean_state)
    assert_actors_succeeded(outcome)
    assert_schedule_executed(outcome, expected_release_order("S1"))

    assert outcome.result.verdict is Verdict.VIOLATION, (
        "S1 did not violate. Either the projection caught up early, or the agent "
        "is reading the authoritative stores instead of the view it was given."
    )
    assert outcome.result.committed_total == Decimal("1100.00")
    assert outcome.result.realized_overage == Decimal("100.00")


def test_s1_is_strictly_sequential(clean_state):
    """The distinguishing property. B's first action follows A's last.

    If these overlapped, S1 would be P2 wearing a costume and would show nothing
    new.
    """
    outcome = run_schedule("S1", clean_state)
    order = [tuple(r) for r in outcome.release_order]

    a_last = max(i for i, r in enumerate(order) if r[0] == "A")
    b_first = min(i for i, r in enumerate(order) if r[0] == "B")

    assert a_last < b_first, (
        f"A and B interleaved (A last at {a_last}, B first at {b_first}) -- "
        "S1 must be strictly sequential or it proves nothing P2 did not"
    )


def test_s1c_is_clean_when_the_projection_has_caught_up(clean_state):
    """Same schedule, same amounts, same policy. Only the catch-up moved."""
    outcome = run_schedule("S1C", clean_state)
    assert_actors_succeeded(outcome)

    assert outcome.result.verdict is Verdict.CLEAN, (
        "S1C violated -- if the control also fails, the projection catch-up is "
        "broken and S1 proves nothing"
    )
    assert outcome.result.committed_total == Decimal("600.00")


def test_s1_and_s1c_differ_only_in_when_the_projection_catches_up(clean_state):
    """The contrast made explicit and checkable."""
    from schedules.runner import load

    s1, s1c = load("S1"), load("S1C")

    assert [a["amount"] for a in s1["actors"] if "amount" in a] == [
        a["amount"] for a in s1c["actors"] if "amount" in a
    ]
    assert s1["authorized_compensation"] == s1c["authorized_compensation"]
    assert s1["use_projection"] is s1c["use_projection"] is True

    def projector_position(spec):
        return min(i for i, s in enumerate(spec["steps"]) if s[0] == "P")

    def b_first_position(spec):
        return min(i for i, s in enumerate(spec["steps"]) if s[0] == "B")

    assert projector_position(s1) > b_first_position(s1), "S1: catch-up is late"
    assert projector_position(s1c) < b_first_position(s1c), "S1C: catch-up is early"


def test_s1_leaves_no_waiter_parked(clean_state):
    outcome = run_schedule("S1", clean_state)
    assert outcome.parked_waiters == []


def test_ordinary_monitoring_does_not_see_the_s1_breach(clean_state):
    """H2, measured rather than asserted.

    After S1 the system is, by every conventional signal, healthy: both actors
    succeeded, both events were published and applied, the projection agrees
    with the events it folded in, no duplicate keys, no orphans. A competent
    team's reconciler reports nothing.

    The business state is wrong by 100.

    The reconciler is deliberately not told about the ceiling -- that check is
    the solution under test, and giving it to the baseline would make this
    finding circular. So this measures what ordinary monitoring actually sees,
    which is the point.
    """
    from apps.reconciliation.worker import reconcile

    outcome = run_schedule("S1", clean_state)
    assert_actors_succeeded(outcome)

    assert outcome.result.verdict is Verdict.VIOLATION
    assert outcome.result.realized_overage == Decimal("100.00")

    report = reconcile("case-s1")

    assert report.clean, (
        "ordinary monitoring reported something -- if it can see this breach, "
        f"the silent-failure finding does not hold. Findings: {report.findings}"
    )


def test_the_contrast_in_one_assertion(clean_state):
    """Every conventional signal green; the money wrong."""
    from apps.reconciliation.worker import reconcile

    outcome = run_schedule("S1", clean_state)

    signals = {
        "all actors succeeded": all(o[0] == "ok" for o in outcome.actor_outcomes),
        "schedule executed as declared": [tuple(r) for r in outcome.release_order]
        == [tuple(s) for s in expected_release_order("S1")],
        "no waiter stranded": outcome.parked_waiters == [],
        "reconciler clean": reconcile("case-s1").clean,
    }
    assert all(signals.values()), signals

    assert outcome.result.verdict is Verdict.VIOLATION, (
        "every conventional signal is green and the business state must still "
        "be wrong -- that gap is the entire Stage 1 result"
    )
