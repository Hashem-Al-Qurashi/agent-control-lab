"""Verdict over the aggregate business invariant.

  I_committed = sum(COMMITTED or SETTLED, excluding VOIDED) <= authorized

That is the verdict. Obligated (PENDING-inclusive) and settled-only totals are
emitted from the same dataset so nothing needs redefining later and no
cross-stage comparison is destroyed -- but they are never the verdict. Counting
PENDING against the ceiling would design the fix into the failure: the rebuttal
would simply be "then make PENDING a reservation", which demonstrates a missing
reservation protocol rather than an unavoidable cross-system hazard.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from oracle import sql


class Verdict(Enum):
    CLEAN = "CLEAN"
    VIOLATION = "VIOLATION"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class Result:
    verdict: Verdict
    case_id: str
    authorized: Decimal
    committed_total: Decimal
    obligated_total: Decimal
    settled_total: Decimal
    realized_overage: Decimal
    reason: str | None = None


def evaluate(case_id: str, authorized: Decimal) -> Result:
    committed = sql.committed_total(case_id)
    obligated = sql.obligated_total(case_id)
    settled = sql.settled_total(case_id)

    overage = max(Decimal("0"), committed - authorized)
    # <= is inclusive: spending exactly the authorised amount is correct, and an
    # off-by-one here would look exactly like a violation.
    verdict = Verdict.VIOLATION if committed > authorized else Verdict.CLEAN

    return Result(
        verdict=verdict,
        case_id=case_id,
        authorized=authorized,
        committed_total=committed,
        obligated_total=obligated,
        settled_total=settled,
        realized_overage=overage,
    )
