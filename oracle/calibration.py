"""Calibration: the oracle proves itself before it is allowed to judge anything.

Plants states whose correct verdict is known by construction, and checks the
oracle returns exactly those verdicts. An oracle never shown to catch a planted
violation, and never shown to pass a planted safe state, is unproven
instrumentation -- and every schedule verdict would inherit that doubt.

Two failure modes are covered deliberately, because they are opposites and a
one-sided check would miss one of them:

  an oracle that never reports a violation  -> P2 passes, thesis looks false
  an oracle that always reports a violation -> P1 fails, rig looks broken

Planted rows are removed afterwards. State left behind by the instrument would
contaminate the run it just certified.

The evaluator is injectable so a deliberately broken oracle can be run through
this. A self-check that cannot fail is not a check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

import psycopg2

from oracle.invariants import Result, Verdict, evaluate
from oracle.quiescence import OWNER_DSNS

CEILING = Decimal("1000.00")


class CalibrationFailed(Exception):
    """The oracle misjudged a state whose verdict is known by construction."""


@dataclass(frozen=True)
class CalibrationCase:
    name: str
    case_id: str
    expected: Verdict
    actual: Verdict


@dataclass
class CalibrationReport:
    cases: list[CalibrationCase] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.expected is c.actual for c in self.cases)


# (name, case_id, billing rows, ledger rows, expected verdict)
_PLANTED = [
    (
        "planted_violation",
        "calib-violation",
        [("600.00", "COMMITTED")],
        [("500.00", "COMMITTED")],
        Verdict.VIOLATION,
    ),
    (
        "planted_safe",
        "calib-safe",
        [("600.00", "COMMITTED")],
        [("300.00", "COMMITTED")],
        Verdict.CLEAN,
    ),
    (
        "planted_voided_is_safe",
        "calib-voided",
        [("600.00", "COMMITTED")],
        [("500.00", "VOIDED")],
        Verdict.CLEAN,
    ),
]

_TABLES = {"billing": "refunds", "ledger": "credits"}


def _plant(service: str, case_id: str, rows: list[tuple[str, str]]) -> None:
    conn = psycopg2.connect(OWNER_DSNS[service])
    try:
        with conn.cursor() as cur:
            for i, (amount, state) in enumerate(rows):
                cur.execute(
                    f"INSERT INTO {_TABLES[service]} "
                    "(case_id, actor_id, idempotency_key, amount, state) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (case_id, "CALIB", f"{case_id}-{service}-{i}", amount, state),
                )
        conn.commit()
    finally:
        conn.close()


def _clear(case_id: str) -> None:
    for service, table in _TABLES.items():
        conn = psycopg2.connect(OWNER_DSNS[service])
        try:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {table} WHERE case_id = %s", (case_id,))
            conn.commit()
        finally:
            conn.close()


def calibrate(
    evaluator: Callable[[str, Decimal], Result] = evaluate
) -> CalibrationReport:
    report = CalibrationReport()

    for name, case_id, billing_rows, ledger_rows, expected in _PLANTED:
        _clear(case_id)
        try:
            _plant("billing", case_id, billing_rows)
            _plant("ledger", case_id, ledger_rows)
            actual = evaluator(case_id, CEILING).verdict
        finally:
            # Always clear, even if the evaluator raised. Instrument state must
            # never contaminate the run it is certifying.
            _clear(case_id)

        report.cases.append(
            CalibrationCase(
                name=name, case_id=case_id, expected=expected, actual=actual
            )
        )

    failures = [c for c in report.cases if c.expected is not c.actual]
    if failures:
        detail = "; ".join(
            f"{c.name}: expected {c.expected.value}, got {c.actual.value}"
            for c in failures
        )
        raise CalibrationFailed(
            f"oracle is not trustworthy -- {detail}. No schedule may run until "
            "calibration passes."
        )
    return report
