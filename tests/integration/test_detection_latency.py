"""How long until the reconciler notices? For the flagship breach: never.

The claim this measures is the most load-bearing one in the repository, and the
most dangerous to assert carelessly. "Ordinary monitoring never detects S1" is a
NULL result, and a null result produced by a broken measurement is
indistinguishable from a null result produced by a real absence.

So the same function is calibrated against a planted drift the reconciler does
catch. If that comes back undetected too, the instrument is broken and the S1
result means nothing. This mirrors the oracle's own calibration gate: an
instrument never shown to detect anything is unproven.
"""

from decimal import Decimal

import pytest

from apps.billing.db import connect as billing_connect
from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from apps.crm.db import connect as crm_connect
from apps.crm.db import run_migrations as crm_migrations
from apps.crm.db import truncate_all as crm_truncate
from apps.ledger.db import run_migrations as ledger_migrations
from apps.ledger.db import truncate_all as ledger_truncate
from libs.clock import FrozenClock
from oracle.detection import measure_detection

CASE = "detect-1"


@pytest.fixture(autouse=True)
def _clean():
    billing_migrations()
    ledger_migrations()
    crm_migrations()
    billing_truncate()
    ledger_truncate()
    crm_truncate()
    yield
    billing_truncate()
    ledger_truncate()
    crm_truncate()


def _commit_refund(amount, key):
    with billing_connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO refunds (case_id, actor_id, idempotency_key, amount, state) "
            "VALUES (%s, 'A', %s, %s, 'COMMITTED')",
            (CASE, key, Decimal(amount)),
        )
        conn.commit()


def _plant_projection_drift(amount):
    """A projection total that disagrees with the events it applied.

    This is a defect the reconciler is built to find, so it is the right
    calibration case: if the instrument cannot see this, it cannot see anything.
    """
    with crm_connect() as conn, conn.cursor() as cur:
        # A projection claiming a total it never applied any events for. This
        # is exactly what _check_drift exists to catch.
        cur.execute(
            "INSERT INTO compensation_projection (case_id, total, events_applied) "
            "VALUES (%s, %s, 1) ON CONFLICT (case_id) DO UPDATE "
            "SET total = EXCLUDED.total, events_applied = 1",
            (CASE, Decimal(amount)),
        )
        conn.commit()


def test_the_instrument_detects_a_defect_it_should_detect():
    """Calibration. Must come first: every result below is void without it."""
    clock = FrozenClock()
    breach_at = clock.now()
    _plant_projection_drift("777.00")
    clock.advance(seconds=42)

    result = measure_detection(CASE, breach_at=breach_at, clock=clock)

    assert result.detected is True, (
        "the reconciler did not report a planted projection drift; the "
        "instrument is broken and no null result from it means anything"
    )
    assert result.delay_seconds == 42.0


def test_a_clean_case_reports_nothing():
    """The other half of calibration: it must not detect what is not there."""
    clock = FrozenClock()

    result = measure_detection(CASE, breach_at=clock.now(), clock=clock)

    assert result.detected is False


def test_the_aggregate_breach_is_never_detected():
    """The finding, measured rather than asserted.

    Two committed refunds totalling $1,100 against a $1,000 ceiling. Every
    service is internally consistent: no lag, no drift, no duplicate keys, no
    orphans. The reconciler is working perfectly and has nothing to say, because
    nothing it checks is wrong.
    """
    clock = FrozenClock()
    _commit_refund("600.00", "d-a")
    _commit_refund("500.00", "d-b")
    breach_at = clock.now()
    clock.advance(seconds=86400)

    result = measure_detection(CASE, breach_at=breach_at, clock=clock)

    assert result.detected is False, (
        f"expected the breach to be invisible to reconciliation; got "
        f"{result.findings}"
    )
    assert result.delay_seconds is None


def test_the_undetected_result_is_reported_as_unbounded_not_zero():
    """A latency of None must never be rendered as 0.

    Averaged into a dashboard, "0 seconds to detect" is the most flattering
    possible number for the worst possible outcome.
    """
    clock = FrozenClock()
    _commit_refund("600.00", "d-a")
    _commit_refund("500.00", "d-b")

    result = measure_detection(CASE, breach_at=clock.now(), clock=clock)

    assert result.summary() == "never detected"


def test_a_detected_result_renders_its_delay():
    clock = FrozenClock()
    breach_at = clock.now()
    _plant_projection_drift("777.00")
    clock.advance(seconds=90)

    assert measure_detection(CASE, breach_at=breach_at, clock=clock).summary() == (
        "detected after 90.0s"
    )
