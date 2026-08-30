"""An approval must not outlive the decision it was granted for.

The gap: approval authority is carried as a token scope, so it lives as long as
the session — an hour by default. A human approving one $600 refund is not
approving whatever that agent does for the next hour, and an agent that acts on
an approval granted long ago is acting on authority nobody currently intends it
to have.

This is the bounded-time class from INVARIANT-CATALOG applied to authorisation
rather than to money.
"""

from decimal import Decimal

import pytest

from libs.approvals import (
    ApprovalExpired,
    ApprovalGrant,
    ApprovalNotApplicable,
    check_approval,
    issue_approval,
)
from libs.clock import FrozenClock


def _grant(clock, valid_for=300, case_id="c1", action="refund", max_amount="600.00"):
    return issue_approval(
        case_id=case_id,
        action=action,
        max_amount=Decimal(max_amount),
        valid_for_seconds=valid_for,
        clock=clock,
    )


def test_a_fresh_grant_authorises_its_own_action():
    clock = FrozenClock()
    grant = _grant(clock)

    check_approval(grant, case_id="c1", action="refund",
                   amount=Decimal("600.00"), clock=clock)


def test_a_grant_past_its_window_is_refused():
    """The finding. The agent was authorised; it no longer is."""
    clock = FrozenClock()
    grant = _grant(clock, valid_for=300)
    clock.advance(seconds=301)

    with pytest.raises(ApprovalExpired):
        check_approval(grant, case_id="c1", action="refund",
                       amount=Decimal("600.00"), clock=clock)


def test_a_grant_is_valid_up_to_and_including_its_deadline():
    """Inclusive, deliberately. An off-by-one here refuses work that was
    genuinely approved, which is the ACL-F16 failure in a different costume."""
    clock = FrozenClock()
    grant = _grant(clock, valid_for=300)
    clock.advance(seconds=300)

    check_approval(grant, case_id="c1", action="refund",
                   amount=Decimal("600.00"), clock=clock)


def test_a_grant_for_another_case_does_not_transfer():
    """Approval reuse. Without binding, one approval authorises every case."""
    clock = FrozenClock()
    grant = _grant(clock, case_id="c1")

    with pytest.raises(ApprovalNotApplicable):
        check_approval(grant, case_id="c2", action="refund",
                       amount=Decimal("600.00"), clock=clock)


def test_a_grant_for_another_action_does_not_transfer():
    clock = FrozenClock()
    grant = _grant(clock, action="refund")

    with pytest.raises(ApprovalNotApplicable):
        check_approval(grant, case_id="c1", action="credit",
                       amount=Decimal("600.00"), clock=clock)


def test_a_grant_does_not_authorise_more_than_it_approved():
    """A manager approving $600 has not approved $900."""
    clock = FrozenClock()
    grant = _grant(clock, max_amount="600.00")

    with pytest.raises(ApprovalNotApplicable):
        check_approval(grant, case_id="c1", action="refund",
                       amount=Decimal("900.00"), clock=clock)


def test_a_grant_authorises_less_than_it_approved():
    clock = FrozenClock()
    grant = _grant(clock, max_amount="600.00")

    check_approval(grant, case_id="c1", action="refund",
                   amount=Decimal("400.00"), clock=clock)


def test_a_grant_without_a_window_is_refused_rather_than_trusted_forever():
    """Fail closed. An approval with no deadline never expires, and the check
    would pass by not applying -- the same defect shape as a token whose `exp`
    is verified only when present.
    """
    clock = FrozenClock()
    forever = ApprovalGrant(
        case_id="c1", action="refund", max_amount=Decimal("600.00"),
        granted_at=clock.now(), expires_at=None,
    )

    with pytest.raises(ApprovalExpired):
        check_approval(forever, case_id="c1", action="refund",
                       amount=Decimal("600.00"), clock=clock)
