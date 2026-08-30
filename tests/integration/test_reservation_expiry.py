"""Reservations expire, and abandoned budget becomes recoverable.

The gap this closes: a hold taken by an agent that then dies is held forever.
`THREAT-MODEL.md` T9 records it, and the property that makes it dangerous is
that the resulting refusal looks *exactly* like the control working correctly,
so nobody investigates.

Bounded-time is the fifth invariant class in INVARIANT-CATALOG.md and was the
one with no enforcing mechanism. This is that mechanism.
"""

from decimal import Decimal

import pytest

from apps.control.db import connect, run_migrations, truncate_all
from apps.control.expiry import expire_due
from libs.clock import FrozenClock

CEILING = Decimal("1000.00")


@pytest.fixture(autouse=True)
def _clean():
    run_migrations()
    truncate_all()
    yield
    truncate_all()


def _hold(case_id, amount, key, clock, ttl_seconds=None, state="HELD"):
    """Insert a hold directly, so a test can place its deadline precisely."""
    expires_at = None
    if ttl_seconds is not None:
        expires_at = clock.now() + __import__("datetime").timedelta(seconds=ttl_seconds)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO reservations "
            "(case_id, actor_id, idempotency_key, amount, state, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (case_id, "A", key, amount, state, expires_at),
        )
        return cur.fetchone()[0]


def _held_total(case_id):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM reservations "
            "WHERE case_id = %s AND state IN ('HELD', 'COMMITTED')",
            (case_id,),
        )
        return cur.fetchone()[0]


def _state(reservation_id):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT state FROM reservations WHERE id = %s", (reservation_id,))
        return cur.fetchone()[0]


def _reap(clock):
    with connect() as conn, conn.cursor() as cur:
        count = expire_due(cur, clock)
        conn.commit()
        return count


def test_an_unexpired_hold_still_occupies_its_budget():
    """The control must not become permissive just because expiry exists."""
    clock = FrozenClock()
    _hold("c1", Decimal("600.00"), "k1", clock, ttl_seconds=300)

    clock.advance(seconds=299)

    assert _reap(clock) == 0
    assert _held_total("c1") == Decimal("600.00")


def test_an_expired_hold_stops_occupying_its_budget():
    clock = FrozenClock()
    _hold("c1", Decimal("600.00"), "k1", clock, ttl_seconds=300)

    clock.advance(seconds=301)

    assert _reap(clock) == 1
    assert _held_total("c1") == Decimal("0")


def test_a_committed_hold_is_never_reaped():
    """Money that moved cannot be un-spent by a timer.

    Reaping a COMMITTED hold would free budget that was genuinely consumed, and
    the next agent would be authorised to overspend -- the control causing the
    exact breach it exists to prevent.
    """
    clock = FrozenClock()
    reservation = _hold("c1", Decimal("600.00"), "k1", clock, ttl_seconds=1,
                        state="COMMITTED")

    clock.advance(seconds=9999)
    _reap(clock)

    assert _state(reservation) == "COMMITTED"
    assert _held_total("c1") == Decimal("600.00")


def test_a_hold_with_no_deadline_is_never_reaped():
    """Absence of a deadline is not a deadline in the past."""
    clock = FrozenClock()
    reservation = _hold("c1", Decimal("600.00"), "k1", clock, ttl_seconds=None)

    clock.advance(seconds=9999)

    assert _reap(clock) == 0
    assert _state(reservation) == "HELD"


def test_reaping_is_idempotent():
    clock = FrozenClock()
    _hold("c1", Decimal("600.00"), "k1", clock, ttl_seconds=10)
    clock.advance(seconds=11)

    assert _reap(clock) == 1
    assert _reap(clock) == 0


def test_an_expired_hold_is_distinguishable_from_a_released_one():
    """Different causes must not share a state.

    A hold the agent released is a normal ending. A hold the reaper took back is
    evidence an agent died mid-flight -- and if both read as RELEASED, the
    second one is invisible in the decision log.
    """
    clock = FrozenClock()
    reservation = _hold("c1", Decimal("600.00"), "k1", clock, ttl_seconds=10)
    clock.advance(seconds=11)
    _reap(clock)

    assert _state(reservation) == "EXPIRED"


def test_expiry_frees_exactly_the_expired_hold():
    """Two holds, one deadline passed. The other must be untouched."""
    clock = FrozenClock()
    short = _hold("c1", Decimal("400.00"), "k1", clock, ttl_seconds=10)
    long = _hold("c1", Decimal("300.00"), "k2", clock, ttl_seconds=600)

    clock.advance(seconds=11)
    _reap(clock)

    assert _state(short) == "EXPIRED"
    assert _state(long) == "HELD"
    assert _held_total("c1") == Decimal("300.00")


# --- the reserve path must reclaim before it refuses ----------------------


def _reserve(case_id, amount, key, ttl_seconds=None):
    from apps.control.main import ReserveRequest, reserve
    from libs.barrier.middleware import actor_identity

    request = ReserveRequest(
        case_id=case_id,
        amount=Decimal(amount),
        idempotency_key=key,
        authorized_compensation=CEILING,
        ttl_seconds=ttl_seconds,
    )
    with actor_identity("B", "EXPIRY"):
        return reserve(request)


def test_a_live_agent_is_refused_while_the_hold_is_still_valid(monkeypatch):
    """The negative control. Expiry must not make the authority permissive.

    The service clock is pinned to the same instant the hold was stamped from.
    Leaving the service on real time while the fixture stamps deadlines from a
    frozen epoch makes every hold retroactively ancient, so it is reaped
    immediately and this test passes for entirely the wrong reason -- which is
    exactly what happened the first time it was written.
    """
    import fastapi

    import apps.control.main as control

    clock = FrozenClock()
    monkeypatch.setattr(control, "_clock", clock)
    _hold("c1", Decimal("600.00"), "k1", clock, ttl_seconds=300)

    with pytest.raises(fastapi.HTTPException) as refused:
        _reserve("c1", "500.00", "k2")

    assert refused.value.status_code == 409


def test_a_live_agent_succeeds_once_the_dead_agents_hold_has_lapsed(monkeypatch):
    """ACL-F16 resolved: budget occupied by nothing is reclaimed on contention.

    Reclaiming inside the reservation lock rather than only from a background
    loop matters -- a purely background reaper leaves a window as long as its
    interval, and that window is indistinguishable from a correct refusal.
    """
    import apps.control.main as control

    clock = FrozenClock()
    _hold("c1", Decimal("600.00"), "k1", clock, ttl_seconds=300)

    # Swap the service's clock past the deadline. No sleeping: the assertion is
    # that the reserve path consults a deadline, not that time passed.
    lapsed = FrozenClock()
    lapsed.advance(seconds=301)
    monkeypatch.setattr(control, "_clock", lapsed)

    granted = _reserve("c1", "500.00", "k2")

    assert granted["granted"] is True


def test_a_reservation_records_its_own_deadline():
    _reserve("c2", "100.00", "k9", ttl_seconds=120)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT expires_at FROM reservations WHERE idempotency_key = 'k9'")
        assert cur.fetchone()[0] is not None


def test_a_reservation_without_a_ttl_has_no_deadline():
    """Opt-in. Existing callers keep the behaviour they were written against."""
    _reserve("c3", "100.00", "k10")

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT expires_at FROM reservations WHERE idempotency_key = 'k10'")
        assert cur.fetchone()[0] is None


# --- expiry racing a live acquisition ------------------------------------


def test_the_ceiling_holds_when_expiry_races_live_acquisitions(monkeypatch):
    """Contended expiry, not idle reclaim.

    Every other expiry test here reclaims a hold while nothing else is
    happening, and CAPACITY.md's runs all had zero holds to reclaim. Gate 4's
    decision_framework flagged exactly this gap: expiry racing an in-flight
    acquisition is the case where a reaper outside the lock would be unsafe,
    and it was untested.

    A lapsed $600 hold, then twenty agents contending at once for $100 each.
    The reclaimed budget must be spendable exactly once over: ten grants, not
    eleven, and not ten-plus-the-reclaimed-six.
    """
    import concurrent.futures as cf

    import fastapi

    import apps.control.main as control

    lapsed = FrozenClock()
    lapsed.advance(seconds=1000)
    # The hold's deadline is in the past relative to the service's clock.
    _hold("race", Decimal("600.00"), "race-dead", FrozenClock(), ttl_seconds=10)
    monkeypatch.setattr(control, "_clock", lapsed)

    def attempt(n):
        from apps.control.main import ReserveRequest, reserve
        from libs.barrier.middleware import actor_identity

        with actor_identity(f"A{n}", "RACE"):
            try:
                reserve(ReserveRequest(
                    case_id="race", amount=Decimal("100.00"),
                    idempotency_key=f"race-{n}",
                    authorized_compensation=CEILING,
                ))
                return True
            except fastapi.HTTPException:
                return False

    with cf.ThreadPoolExecutor(max_workers=20) as pool:
        granted = sum(pool.map(attempt, range(20)))

    assert granted == 10, (
        f"expected exactly ten grants against the reclaimed ceiling, got {granted}"
    )

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM reservations "
            "WHERE case_id = 'race' AND state IN ('HELD', 'COMMITTED')"
        )
        assert cur.fetchone()[0] == Decimal("1000.00")


def test_the_lapsed_hold_is_reaped_exactly_once_under_contention(monkeypatch):
    """Twenty concurrent reservers each run the reaper inside the lock.

    If reaping were not idempotent under contention the budget would be
    returned repeatedly -- the over-grant its sibling asserts against, reached
    from the other direction.

    Self-contained: an earlier version read state left by the previous test,
    which the autouse truncation removes. A test that depends on another test's
    leftovers passes or fails on ordering rather than on behaviour.
    """
    import concurrent.futures as cf

    import fastapi

    import apps.control.main as control

    lapsed = FrozenClock()
    lapsed.advance(seconds=1000)
    _hold("race2", Decimal("600.00"), "race2-dead", FrozenClock(), ttl_seconds=10)
    monkeypatch.setattr(control, "_clock", lapsed)

    def attempt(n):
        from apps.control.main import ReserveRequest, reserve
        from libs.barrier.middleware import actor_identity

        with actor_identity(f"B{n}", "RACE"):
            try:
                reserve(ReserveRequest(
                    case_id="race2", amount=Decimal("100.00"),
                    idempotency_key=f"race2-{n}",
                    authorized_compensation=CEILING,
                ))
            except fastapi.HTTPException:
                pass

    with cf.ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(attempt, range(20)))

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM reservations "
            "WHERE case_id = 'race2' AND state = 'EXPIRED'"
        )
        assert cur.fetchone()[0] == 1, "the lapsed hold was reaped more than once"
