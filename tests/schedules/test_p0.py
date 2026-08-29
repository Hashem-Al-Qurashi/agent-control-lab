"""P0 -- the same race as P2, with a coordination primitive. MUST PASS.

Identical interleaving, identical policy, identical amounts. The only difference
is an interface that can see the aggregate.

This is what defeats the strawman. Without it the rebuttal lands: "you built a
system with no coordinator and then showed it doesn't coordinate." With it, the
same diligent policy given a coordination interface does not breach the ceiling
under the very schedule that breaks it otherwise.
"""

from decimal import Decimal

from oracle.invariants import Verdict
from schedules.runner import run_schedule


def test_p0_does_not_violate_under_p2s_interleaving(clean_state):
    outcome = run_schedule("P0", clean_state)

    assert outcome.result.verdict is Verdict.CLEAN, (
        "the reservation failed to prevent the breach -- if this violates, the "
        "coordination primitive is broken and P0 proves nothing"
    )
    assert outcome.result.committed_total <= Decimal("1000.00")


def test_p0_admits_exactly_one_of_the_two_actors(clean_state):
    """One actor is refused. Refusal is a correct outcome, not an error."""
    outcome = run_schedule("P0", clean_state)

    assert outcome.result.committed_total == Decimal("600.00"), (
        "A reserves first by declared order and commits; B is then refused and "
        f"declines. Committed total was {outcome.result.committed_total}"
    )


def test_p0_and_p2_differ_only_in_the_available_interface(clean_state):
    """The contrast made explicit: same steps, same amounts, opposite outcome."""
    from schedules.runner import load

    p0, p2 = load("P0"), load("P2")

    assert p0["steps"][:4] == p2["steps"][:4]  # identical race up to the act
    assert p0["authorized_compensation"] == p2["authorized_compensation"]
    assert [a["amount"] for a in p0["actors"]] == [a["amount"] for a in p2["actors"]]
    assert p0.get("use_reservations") is True
    assert p2.get("use_reservations") is None


def test_p0_refusal_is_not_an_actor_error(clean_state):
    """A refused reservation must not look like a crash."""
    outcome = run_schedule("P0", clean_state)

    assert all(o[0] == "ok" for o in outcome.actor_outcomes), outcome.actor_outcomes
