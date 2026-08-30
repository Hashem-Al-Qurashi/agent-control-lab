"""ACL-F18 -- expiry returns budget that was already spent.

The control from Phase 2 creates a failure in Phase 3.

An agent reserves, commits its effect, and dies before committing the hold. The
money has moved; the reservation is still HELD. `expire_due` reaps HELD rows, so
the reaper returns that budget to the ceiling and a later agent may legitimately
spend it a second time.

This is not a crash SIMULATION dressed as a crash: the state it constructs --
effect durable, hold still HELD -- is precisely the state `run_case` occupies
between `target.create()` and `clients.commit()`. What is modelled is the agent
never returning, which is what dying looks like from every other process.

The remedy is recursive, which is why this entry earns its place: before
releasing a lapsed hold, something must establish whether that hold's action
landed -- and that requires seeing across Billing and Ledger from the control
service, the same cross-service visibility the whole lab is about.
"""

from decimal import Decimal

import pytest

import apps.control.main as control
from apps.billing.db import connect as billing_connect
from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from apps.control.db import connect, run_migrations, truncate_all
from apps.control.main import ReserveRequest, reserve
from libs.barrier.middleware import actor_identity
from libs.clock import FrozenClock

CEILING = Decimal("1000.00")
CASE = "crash-1"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("ACL_ENFORCE_POLICY", "0")
    run_migrations()
    billing_migrations()
    truncate_all()
    billing_truncate()
    yield
    truncate_all()
    billing_truncate()


def _spend(actor, amount, key, ttl_seconds=None):
    """Reserve, then land the effect. The hold is deliberately NOT committed."""
    with actor_identity(actor, "S9"):
        granted = reserve(ReserveRequest(
            case_id=CASE, amount=Decimal(amount), idempotency_key=key,
            authorized_compensation=CEILING, ttl_seconds=ttl_seconds,
        ))
    with billing_connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO refunds (case_id, actor_id, idempotency_key, amount, state) "
            "VALUES (%s, %s, %s, %s, 'COMMITTED')",
            (CASE, actor, key, Decimal(amount)),
        )
        conn.commit()
    return granted


def _committed_money():
    with billing_connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM refunds "
            "WHERE case_id = %s AND state IN ('COMMITTED', 'SETTLED')",
            (CASE,),
        )
        return cur.fetchone()[0]


def _reservation_state(key):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM reservations WHERE idempotency_key = %s", (key,)
        )
        return cur.fetchone()[0]


def test_the_crash_window_leaves_money_spent_against_an_uncommitted_hold(monkeypatch):
    """Anomaly A1 -- the precondition. Should exist transiently, never durably."""
    pinned = FrozenClock()
    monkeypatch.setattr(control, "_clock", pinned)

    _spend("A", "600.00", "crash-a", ttl_seconds=300)

    assert _committed_money() == Decimal("600.00")
    assert _reservation_state("crash-a") == "HELD"


def test_the_reaper_frees_budget_that_was_already_spent(monkeypatch):
    """Anomaly A2 -- must never exist, and currently does."""
    pinned = FrozenClock()
    monkeypatch.setattr(control, "_clock", pinned)
    _spend("A", "600.00", "crash-a", ttl_seconds=300)

    lapsed = FrozenClock()
    lapsed.advance(seconds=301)
    monkeypatch.setattr(control, "_clock", lapsed)
    with actor_identity("B", "S9"):
        with pytest.raises(Exception):
            # Any reservation attempt triggers the in-lock reap.
            reserve(ReserveRequest(
                case_id=CASE, amount=Decimal("99999.00"),
                idempotency_key="probe", authorized_compensation=CEILING,
            ))

    assert _reservation_state("crash-a") == "EXPIRED", (
        "the hold was not reaped; the over-spend path is not reachable this way"
    )
    assert _committed_money() == Decimal("600.00"), "the money is still spent"


def test_a_second_agent_can_then_overspend_the_ceiling(monkeypatch):
    """Anomaly A3 -- the breach itself.

    $600 is genuinely spent. After the reaper frees the hold, B is granted $500
    against a $1,000 ceiling. Total $1,100, with every reservation individually
    correct at the moment it was decided.
    """
    pinned = FrozenClock()
    monkeypatch.setattr(control, "_clock", pinned)
    _spend("A", "600.00", "crash-a", ttl_seconds=300)

    lapsed = FrozenClock()
    lapsed.advance(seconds=301)
    monkeypatch.setattr(control, "_clock", lapsed)
    granted = _spend("B", "500.00", "crash-b")

    assert granted["granted"] is True
    assert _committed_money() == Decimal("1100.00"), (
        "expected the reaper to have enabled an over-spend"
    )


def test_the_control_service_alone_cannot_detect_this(monkeypatch):
    """Why the remedy is recursive, asserted rather than argued.

    Everything the control service can see says it behaved correctly: a hold
    lapsed, budget returned, a later request fitted. The information that would
    have stopped it -- that the lapsed hold's action landed -- lives in Billing,
    which the control service cannot read.
    """
    pinned = FrozenClock()
    monkeypatch.setattr(control, "_clock", pinned)
    _spend("A", "600.00", "crash-a", ttl_seconds=300)
    lapsed = FrozenClock()
    lapsed.advance(seconds=301)
    monkeypatch.setattr(control, "_clock", lapsed)
    _spend("B", "500.00", "crash-b")

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM reservations "
            "WHERE case_id = %s AND state IN ('HELD', 'COMMITTED')",
            (CASE,),
        )
        visible = cur.fetchone()[0]

    assert visible == Decimal("500.00"), (
        "the control service sees only 500 held; the 600 that was actually "
        "spent is invisible to it"
    )
    assert _committed_money() == Decimal("1100.00")


# --- the control: detection, because prevention is not available here -----


def test_the_reconciler_reports_the_spent_expired_hold(monkeypatch):
    """The fix, and it is DETECTION rather than prevention.

    There is no fix available inside the control service alone. It cannot read
    Billing, so it cannot know whether a lapsing hold's action landed. Its two
    options are both failures: free the budget (ACL-F18, an invisible
    over-spend) or refuse to free it (ACL-F16, an invisible stuck hold). The
    control gets to CHOOSE which failure it has, and that is the honest
    statement of the trade-off.

    Eliminating both requires something with visibility across the control
    service and the effect stores -- which is what the reconciler already is,
    and which is the thing this whole lab argues you need.
    """
    from apps.reconciliation.worker import FindingType, reconcile

    pinned = FrozenClock()
    monkeypatch.setattr(control, "_clock", pinned)
    _spend("A", "600.00", "crash-a", ttl_seconds=300)
    lapsed = FrozenClock()
    lapsed.advance(seconds=301)
    monkeypatch.setattr(control, "_clock", lapsed)
    _spend("B", "500.00", "crash-b")

    report = reconcile(CASE)
    spent = [
        f for f in report.findings
        if f.type is FindingType.SPENT_EXPIRED_HOLD
    ]

    assert spent, (
        f"the over-spend went undetected; findings were {report.findings}"
    )
    assert "crash-a" in spent[0].detail


def test_a_normally_expired_hold_is_not_reported(monkeypatch):
    """The negative control. An abandoned hold whose action never landed is
    ACL-F16 working as intended, and must not be flagged as an over-spend."""
    from apps.reconciliation.worker import FindingType, reconcile

    pinned = FrozenClock()
    monkeypatch.setattr(control, "_clock", pinned)
    with actor_identity("A", "S9"):
        reserve(ReserveRequest(
            case_id=CASE, amount=Decimal("600.00"), idempotency_key="clean-a",
            authorized_compensation=CEILING, ttl_seconds=300,
        ))
    lapsed = FrozenClock()
    lapsed.advance(seconds=301)
    monkeypatch.setattr(control, "_clock", lapsed)
    with actor_identity("B", "S9"):
        reserve(ReserveRequest(
            case_id=CASE, amount=Decimal("500.00"), idempotency_key="clean-b",
            authorized_compensation=CEILING,
        ))

    report = reconcile(CASE)

    assert not [
        f for f in report.findings if f.type is FindingType.SPENT_EXPIRED_HOLD
    ], "no money was spent; there is nothing to report"


def test_a_live_hold_whose_effect_landed_is_not_reported(monkeypatch):
    """Anomaly A1: this state is NORMAL, transiently.

    Between `target.create()` and `clients.commit()` every successful agent has
    a HELD reservation whose effect has landed. Reporting that would fire on
    every action the system takes, and an alert that fires constantly is an
    alert nobody reads.

    Added because mutation testing found it: dropping `state = 'EXPIRED'` from
    the detector changed no test, which meant nothing was pinning the
    distinction between a lapsed hold and a live one.
    """
    from apps.reconciliation.worker import FindingType, reconcile

    pinned = FrozenClock()
    monkeypatch.setattr(control, "_clock", pinned)

    # Reserve and land the effect, without committing the hold and without
    # letting any deadline pass -- the ordinary in-flight state.
    _spend("A", "600.00", "live-a", ttl_seconds=300)

    report = reconcile(CASE)

    assert not [
        f for f in report.findings if f.type is FindingType.SPENT_EXPIRED_HOLD
    ], (
        "a live in-flight hold was reported as a spent-expired one; this would "
        f"fire on every successful action: {report.findings}"
    )
