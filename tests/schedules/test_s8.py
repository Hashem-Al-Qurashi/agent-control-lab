"""S8 -- an abandoned hold refuses an action the aggregate permits.

The failure with the opposite sign. Everywhere else in this lab the money moves
when it should not; here it does not move when it should.

Agent A reserves budget and never comes back. Nothing is committed, so the true
aggregate is zero and B's request is entirely within the ceiling. B is refused
anyway, by budget occupied by nothing.

**The property that makes this dangerous is that the refusal is correct-looking.**
A 409 from the coordination authority is exactly what a legitimate refusal looks
like, so nobody investigates. THREAT-MODEL.md T9 records it; until now nothing
reproduced it.

This models an agent that abandons -- returns without acting and without
releasing. A hard crash is S9's subject; for budget purposes the two are
identical, and abandonment is the honest thing to script.
"""

from decimal import Decimal

import fastapi
import pytest

from oracle.invariants import Verdict
from schedules.runner import run_schedule


@pytest.fixture()
def s8(clean_state):
    return run_schedule("S8", clean_state)


def test_s8_leaves_a_hold_that_nothing_will_release(s8):
    from apps.control.db import connect

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM reservations "
            "WHERE case_id = %s AND state = 'HELD'",
            (s8.result.case_id,),
        )
        assert cur.fetchone()[0] == Decimal("600.00"), (
            "A's hold should still be outstanding -- it abandoned without "
            "releasing, which is the whole premise"
        )


def test_s8_committed_nothing(s8):
    """The aggregate is zero, so B's request was always within the ceiling."""
    assert s8.result.committed_total == Decimal("0")


def test_s8_refused_an_action_the_ceiling_permitted(s8):
    """The finding. B asked for 500 against a 1000 ceiling with 0 committed.

    Asserted three ways, because "both actors returned ok" would also be true of
    a run where B simply never executed.
    """
    from apps.ledger.db import connect

    assert all(status == "ok" for status, *_ in s8.actor_outcomes), (
        f"B declines; it must not error: {s8.actor_outcomes}"
    )

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM credits WHERE case_id = %s", (s8.result.case_id,)
        )
        assert cur.fetchone()[0] == 0, "B acted; then it was not refused"

    assert s8.release_order, "the schedule did not execute; the result is void"


def test_without_the_abandoned_hold_the_same_request_succeeds(clean_state):
    """The negative control, and the whole argument.

    B's request is unchanged. The only difference is whether a dead agent is
    still holding budget. If this failed too, S8 would be showing an ordinary
    over-ceiling refusal rather than a leaked hold.
    """
    from apps.control.main import ReserveRequest, reserve
    from libs.barrier.middleware import actor_identity

    with actor_identity("B", "S8"):
        granted = reserve(
            ReserveRequest(
                case_id="s8-control",
                amount=Decimal("500.00"),
                idempotency_key="s8-control-b",
                authorized_compensation=Decimal("1000.00"),
            )
        )

    assert granted["granted"] is True


def test_expiry_is_what_makes_the_budget_recoverable(clean_state, monkeypatch):
    """The fix, on the same shape S8 demonstrates.

    A holds with a deadline and abandons. Once the deadline passes, B's
    identical request is granted -- so the leaked budget is recoverable rather
    than lost until someone notices.
    """
    import apps.control.main as control
    from apps.control.main import ReserveRequest, reserve
    from libs.barrier.middleware import actor_identity
    from libs.clock import FrozenClock

    pinned = FrozenClock()
    monkeypatch.setattr(control, "_clock", pinned)
    with actor_identity("A", "S8"):
        reserve(ReserveRequest(
            case_id="s8-expiry", amount=Decimal("600.00"),
            idempotency_key="s8-expiry-a",
            authorized_compensation=Decimal("1000.00"), ttl_seconds=300,
        ))

    lapsed = FrozenClock()
    lapsed.advance(seconds=301)
    monkeypatch.setattr(control, "_clock", lapsed)

    with actor_identity("B", "S8"):
        granted = reserve(ReserveRequest(
            case_id="s8-expiry", amount=Decimal("500.00"),
            idempotency_key="s8-expiry-b",
            authorized_compensation=Decimal("1000.00"),
        ))

    assert granted["granted"] is True


def test_s8_verdict_is_clean_and_that_is_the_problem(s8):
    """The oracle checks whether too much was spent. Too little is invisible to
    it, which is why this failure needs its own detection and not a tighter
    version of the existing one."""
    assert s8.result.verdict is Verdict.CLEAN


def test_s8_leaves_no_waiter_parked(s8):
    assert s8.parked_waiters == []


def test_the_refusal_is_indistinguishable_from_a_correct_one(clean_state):
    """Asserted, because the indistinguishability IS the finding.

    If a leaked hold produced a distinctive error, an operator would notice it.
    It produces a 409 with the same shape as the refusal that protects the
    ceiling, so it reads as the control doing its job.
    """
    from apps.control.main import ReserveRequest, reserve
    from libs.barrier.middleware import actor_identity

    request = ReserveRequest(
        case_id="s8-shape",
        amount=Decimal("500.00"),
        idempotency_key="s8-shape-b",
        authorized_compensation=Decimal("1000.00"),
    )
    with actor_identity("A", "S8"):
        reserve(
            ReserveRequest(
                case_id="s8-shape",
                amount=Decimal("600.00"),
                idempotency_key="s8-shape-a",
                authorized_compensation=Decimal("1000.00"),
            )
        )
    with actor_identity("B", "S8"), pytest.raises(fastapi.HTTPException) as refused:
        reserve(request)

    assert refused.value.status_code == 409
    assert "exceed" in refused.value.detail
