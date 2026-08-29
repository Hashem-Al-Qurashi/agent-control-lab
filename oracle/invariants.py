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


def _duplicated_effect_keys(case_id: str) -> list[str]:
    """Idempotency keys that produced more than one committed economic effect.

    Only reachable if a service's idempotency broke. VOIDED rows are excluded
    because a voided row is not an economic effect and so cannot be a double one.
    """
    duplicated = []
    for key, rows in sql.rows_by_idempotency_key(case_id).items():
        effects = [r for r in rows if r[3] in sql.VERDICT_STATES]
        if len(effects) > 1:
            duplicated.append(key)
    return sorted(duplicated)


def evaluate(case_id: str, authorized: Decimal) -> Result:
    committed = sql.committed_total(case_id)
    obligated = sql.obligated_total(case_id)
    settled = sql.settled_total(case_id)
    overage = max(Decimal("0"), committed - authorized)

    # Checked BEFORE the ceiling comparison. One logical decision that produced
    # two economic effects is a rig defect, and reporting it as a violation would
    # be the most damaging false positive available -- it has the exact shape of
    # the result being claimed.
    duplicated = _duplicated_effect_keys(case_id)
    if duplicated:
        return Result(
            verdict=Verdict.INCONCLUSIVE,
            case_id=case_id,
            authorized=authorized,
            committed_total=committed,
            obligated_total=obligated,
            settled_total=settled,
            realized_overage=overage,
            reason=(
                f"broken service idempotency: key(s) {duplicated} produced more "
                "than one committed effect. This run proves nothing either way."
            ),
        )

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
