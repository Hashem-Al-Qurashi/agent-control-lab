"""Task 15: calibration -- the oracle must prove itself before it judges anything.

An oracle never shown to catch a planted violation, and never shown to pass a
planted safe state, is unproven instrumentation. Every schedule verdict would
inherit that doubt.

Task 14 tests the oracle's logic. This is different in kind: a runnable
precondition that plants known-bad and known-good states and refuses to let any
schedule run until the oracle has demonstrably judged both correctly.

The calibration takes its evaluator as an argument so a deliberately broken
oracle can be run through it. A self-check that cannot fail is not a check.
"""

from decimal import Decimal

import pytest

from oracle.calibration import CalibrationFailed, calibrate
from oracle.invariants import Result, Verdict, evaluate


def test_calibration_passes_with_the_real_oracle():
    report = calibrate()

    assert report.passed
    assert len(report.cases) >= 3
    assert all(c.expected is c.actual for c in report.cases)


def test_calibration_report_names_every_planted_case():
    report = calibrate()
    names = {c.name for c in report.cases}

    assert "planted_violation" in names
    assert "planted_safe" in names
    assert "planted_voided_is_safe" in names


def test_calibration_fails_an_oracle_that_never_reports_violations():
    """The commonest way instrumentation is silently useless."""
    def always_clean(case_id, authorized):
        return Result(
            verdict=Verdict.CLEAN,
            case_id=case_id,
            authorized=authorized,
            committed_total=Decimal("0"),
            obligated_total=Decimal("0"),
            settled_total=Decimal("0"),
            realized_overage=Decimal("0"),
        )

    with pytest.raises(CalibrationFailed) as exc:
        calibrate(evaluator=always_clean)

    assert "planted_violation" in str(exc.value)


def test_calibration_fails_an_oracle_that_reports_everything_as_a_violation():
    """The opposite failure: an oracle that is never wrong because it never passes."""
    def always_violation(case_id, authorized):
        return Result(
            verdict=Verdict.VIOLATION,
            case_id=case_id,
            authorized=authorized,
            committed_total=Decimal("9999"),
            obligated_total=Decimal("9999"),
            settled_total=Decimal("0"),
            realized_overage=Decimal("9999"),
        )

    with pytest.raises(CalibrationFailed) as exc:
        calibrate(evaluator=always_violation)

    assert "planted_safe" in str(exc.value)


def test_calibration_fails_an_oracle_that_ignores_voided_rows():
    """A subtler defect: counts money that was explicitly reversed."""
    def counts_voided(case_id, authorized):
        result = evaluate(case_id, authorized)
        if result.case_id.endswith("voided"):
            return Result(
                verdict=Verdict.VIOLATION,
                case_id=case_id,
                authorized=authorized,
                committed_total=Decimal("1100"),
                obligated_total=Decimal("1100"),
                settled_total=Decimal("0"),
                realized_overage=Decimal("100"),
            )
        return result

    with pytest.raises(CalibrationFailed) as exc:
        calibrate(evaluator=counts_voided)

    assert "planted_voided_is_safe" in str(exc.value)


def test_calibration_leaves_no_planted_rows_behind():
    """Planted state must not leak into the run it is certifying."""
    from oracle import sql

    calibrate()

    for case in ("calib-violation", "calib-safe", "calib-voided"):
        assert sql.committed_total(case) == Decimal("0"), (
            f"calibration left rows behind for {case}"
        )
