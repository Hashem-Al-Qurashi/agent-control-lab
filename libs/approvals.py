"""Approvals that expire, and that only authorise what they approved.

Approval authority in this lab was a token scope, so it lived as long as the
session. A human approving one $600 refund is not approving whatever that agent
does for the next hour, and an agent acting on an approval granted long ago is
acting on authority nobody currently intends it to have.

Two properties, both bounded rather than open-ended:

  a grant expires          -- bounded-time, the fifth invariant class
  a grant is bound         -- to one case, one action, one ceiling

The second matters as much as the first. An unbound approval is a master key:
approve one refund and every later action is authorised by the same grant.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from libs.clock import Clock


class ApprovalExpired(Exception):
    """The grant is past its window, or never had one."""


class ApprovalNotApplicable(Exception):
    """The grant does not cover this case, action, or amount."""


@dataclass(frozen=True)
class ApprovalGrant:
    case_id: str
    action: str
    max_amount: Decimal
    granted_at: datetime.datetime
    expires_at: datetime.datetime | None


def issue_approval(
    *,
    case_id: str,
    action: str,
    max_amount: Decimal,
    valid_for_seconds: int,
    clock: Clock,
) -> ApprovalGrant:
    now = clock.now()
    return ApprovalGrant(
        case_id=case_id,
        action=action,
        max_amount=max_amount,
        granted_at=now,
        expires_at=now + datetime.timedelta(seconds=valid_for_seconds),
    )


def check_approval(
    grant: ApprovalGrant,
    *,
    case_id: str,
    action: str,
    amount: Decimal,
    clock: Clock,
) -> None:
    """Raise unless this grant authorises this action right now.

    Fails closed on a grant with no deadline. Treating "no expiry" as "never
    expires" is the same defect as verifying a token's `exp` only when present:
    the check passes by not applying.
    """
    if grant.expires_at is None:
        raise ApprovalExpired(
            "approval carries no validity window; refusing rather than "
            "treating it as valid forever"
        )
    # Inclusive. An off-by-one here refuses work that was genuinely approved,
    # which is ACL-F16's failure -- money that should have moved, not moving.
    if clock.now() > grant.expires_at:
        raise ApprovalExpired(
            f"approval expired at {grant.expires_at.isoformat()}"
        )

    if grant.case_id != case_id:
        raise ApprovalNotApplicable(
            f"approval was granted for case {grant.case_id}, not {case_id}"
        )
    if grant.action != action:
        raise ApprovalNotApplicable(
            f"approval was granted for {grant.action}, not {action}"
        )
    if amount > grant.max_amount:
        raise ApprovalNotApplicable(
            f"approval covers up to {grant.max_amount}, not {amount}"
        )
