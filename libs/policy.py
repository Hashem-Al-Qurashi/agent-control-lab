"""Deterministic per-action authorization.

Evaluated by the service, never by the agent. An LLM that decides its own
permissions has no permissions -- and a deterministic agent that did so would be
no better, because the point is that the decision lives outside the actor.

Deliberately scoped to ONE action at a time. This policy does not and must not
know what else exists for the case. Per-action authorization is not aggregate
correctness, and a policy that enforced both would be the solution under test --
every finding would then be circular, because the system would catch the breach
only by being told the rule we are asking whether anyone knows.

A test asserts this module's source contains no reference to the aggregate.

Substitution recorded in docs/adr/005-identity-and-policy.md: this provides the
PROPERTY OPA would (policy decided outside the application logic, deterministic,
auditable) without running OPA. It does not provide OPA's policy language,
bundle distribution, or decision logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from libs.identity import ActorClaims

# Above this, a single action needs explicit approval authority.
APPROVAL_THRESHOLD = Decimal("500.00")

REQUIRED_SCOPE = {"refund": "refund:create", "credit": "credit:create"}
APPROVED_SCOPE = {"refund": "refund:approved", "credit": "credit:approved"}


class Decision(Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class PolicyDecision:
    outcome: Decision
    reason: str


def evaluate_action(
    claims: ActorClaims, *, action: str, amount: Decimal, tenant: str
) -> PolicyDecision:
    """Decide one action. Same inputs always produce the same decision."""
    # Hard invariant, not a percentage: one cross-tenant action is a breach.
    if claims.tenant != tenant:
        return PolicyDecision(
            Decision.DENY,
            f"tenant mismatch: actor belongs to {claims.tenant}, resource to {tenant}",
        )

    required = REQUIRED_SCOPE.get(action)
    if required is None:
        return PolicyDecision(Decision.DENY, f"unknown action {action!r}")
    if required not in claims.scopes:
        return PolicyDecision(Decision.DENY, f"missing scope {required!r}")

    if amount > APPROVAL_THRESHOLD:
        if APPROVED_SCOPE[action] in claims.scopes:
            return PolicyDecision(
                Decision.ALLOW, "above threshold, approval authority present"
            )
        return PolicyDecision(
            Decision.REQUIRE_APPROVAL,
            f"{amount} exceeds the {APPROVAL_THRESHOLD} single-action threshold",
        )

    return PolicyDecision(Decision.ALLOW, "within single-action authority")
