"""E1 -- every granted feature must be permitted by the case's current plan.

The point of this invariant is that it is not about money. Everything else in
this repo sums Decimals, which invites the reading that the result is about
arithmetic -- that sums are special.

The structure is what matters: an authority owns a fact, a second system acts on
a derived copy, and the copy is behind. A subscription tier breaks exactly the
way a compensation ceiling does.

Set membership, no sums, same failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

FEATURES_BY_PLAN: dict[str, frozenset[str]] = {
    "BASIC": frozenset({"reports"}),
    "PRO": frozenset({"reports", "api", "sso"}),
}


class EntitlementVerdict(Enum):
    CLEAN = "CLEAN"
    VIOLATION = "VIOLATION"


@dataclass(frozen=True)
class EntitlementResult:
    verdict: EntitlementVerdict
    plan: str | None
    granted: frozenset[str]
    unpermitted: set[str]


def evaluate_entitlements(plan: str | None, granted: set[str]) -> EntitlementResult:
    """Grants outside the plan are a breach. Under-granting is not.

    The invariant is a ceiling on authority, not a requirement to use it.
    """
    if plan is None:
        # Fail closed. A missing plan record must not authorise everything --
        # that is how a deleted row becomes a privilege escalation.
        permitted: frozenset[str] = frozenset()
    else:
        # Raises on an unrecognised plan rather than guessing. Guessing what a
        # plan allows is how authority leaks.
        permitted = FEATURES_BY_PLAN[plan]

    unpermitted = set(granted) - set(permitted)
    return EntitlementResult(
        verdict=(
            EntitlementVerdict.VIOLATION if unpermitted else EntitlementVerdict.CLEAN
        ),
        plan=plan,
        granted=frozenset(granted),
        unpermitted=unpermitted,
    )
