"""An approval that has lapsed must not authorise the action it once covered.

Deliberately NOT a barrier schedule. The schedules run services as separate
processes, where a test cannot control the service's clock, so an expiry
schedule would have to sleep -- and a sleeping test proves an interval elapsed,
not that the code consulted a deadline. Expiry is a time question, not an
interleaving question; the barrier answers interleaving questions.

In-process with a frozen clock is the honest way to test this end to end.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.billing.db import run_migrations, truncate_all
from apps.billing.main import app
from libs.approvals import issue_approval
from libs.clock import FrozenClock
from libs.identity import issue_token

ABOVE_THRESHOLD = "600.00"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ACL_ENFORCE_POLICY", "1")
    run_migrations()
    truncate_all()
    with TestClient(app) as c:
        yield c
    truncate_all()


def _headers(scopes=("refund:create",)):
    return {
        "X-Actor-Id": "A",
        "X-Schedule-Id": "APPROVAL",
        "Authorization": f"Bearer {issue_token('A', list(scopes), 'acme')}",
        "X-Tenant-Id": "acme",
    }


def _post(client, amount, key, headers=None):
    return client.post(
        "/refunds",
        json={"case_id": "c1", "amount": amount, "idempotency_key": key},
        headers=headers or _headers(),
    )


def test_an_above_threshold_action_without_approval_is_refused(client):
    """Baseline: the threshold works before expiry is in the picture."""
    assert _post(client, ABOVE_THRESHOLD, "k1").status_code == 403


def test_an_approval_scope_authorises_it(client):
    """The existing mechanism, unchanged."""
    approved = _headers(scopes=("refund:create", "refund:approved"))

    assert _post(client, ABOVE_THRESHOLD, "k2", approved).status_code == 201


def test_a_scope_approval_never_expires_within_the_session(client, monkeypatch):
    """The failure, stated as a test.

    Approval carried as a token scope lives as long as the session. An agent
    that received approval at the start of an hour can still act on it 59
    minutes later, because nothing binds the approval to the decision it was
    granted for.
    """
    import libs.enforcement as enforcement

    late = FrozenClock()
    late.advance(seconds=3000)
    monkeypatch.setattr(enforcement, "_clock", late, raising=False)
    approved = _headers(scopes=("refund:create", "refund:approved"))

    assert _post(client, ABOVE_THRESHOLD, "k3", approved).status_code == 201, (
        "a scope-carried approval is still honoured long after it was granted; "
        "this is the gap a bounded grant closes"
    )


def test_a_bound_grant_authorises_the_action_it_covers():
    clock = FrozenClock()
    from libs.approvals import check_approval

    grant = issue_approval(
        case_id="c1", action="refund", max_amount=Decimal(ABOVE_THRESHOLD),
        valid_for_seconds=300, clock=clock,
    )
    check_approval(grant, case_id="c1", action="refund",
                   amount=Decimal(ABOVE_THRESHOLD), clock=clock)


def test_the_same_grant_is_refused_once_its_window_closes():
    """The control. Same grant, same action, later clock."""
    from libs.approvals import ApprovalExpired, check_approval

    clock = FrozenClock()
    grant = issue_approval(
        case_id="c1", action="refund", max_amount=Decimal(ABOVE_THRESHOLD),
        valid_for_seconds=300, clock=clock,
    )
    clock.advance(seconds=301)

    with pytest.raises(ApprovalExpired):
        check_approval(grant, case_id="c1", action="refund",
                       amount=Decimal(ABOVE_THRESHOLD), clock=clock)
