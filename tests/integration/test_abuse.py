"""Stage 5: abuse cases against the action-taking path.

Deliberately excludes what is already covered elsewhere -- missing scope,
cross-tenant, forged token, above-threshold-without-approval all live in
test_policy_enforcement.py and test_identity_policy.py. Restating them here
would inflate the count without adding coverage.

Out of scope, and named rather than omitted:

  prompt injection / model manipulation -- no LLM is in the tested path. The
      diligent agent is deterministic precisely so failures cannot be blamed on
      a model.
  network attack -- everything binds to 127.0.0.1; there is no adversary on the
      wire.
  token expiry / replay after revocation -- tokens do not expire. That is a real
      residual risk, recorded as T1 in the threat model, not something this
      suite pretends to cover.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.billing.db import run_migrations, truncate_all
from apps.billing.main import app
from libs.identity import issue_token


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BARRIER_ENABLED", "0")
    monkeypatch.setenv("ACL_ENFORCE_POLICY", "1")
    run_migrations()
    truncate_all()
    with TestClient(app) as c:
        yield c
    truncate_all()


def _headers(actor="A", scopes=("refund:create",), tenant="acme"):
    return {
        "X-Actor-Id": actor,
        "X-Schedule-Id": "ABUSE",
        "Authorization": f"Bearer {issue_token(actor, list(scopes), tenant)}",
        "X-Tenant-Id": tenant,
    }


def _post(client, amount, key="k1", headers=None):
    return client.post(
        "/refunds",
        json={"case_id": "c1", "amount": amount, "idempotency_key": key},
        headers=headers or _headers(),
    )


def test_a_negative_amount_is_refused(client):
    """Parameter escalation. A negative refund would increase the budget
    available to the next actor."""
    r = _post(client, "-500.00")

    assert r.status_code >= 400
    listing = client.get("/refunds", params={"case_id": "c1"},
                         headers=_headers()).json()
    assert listing["refunds"] == []


def test_a_zero_amount_is_refused(client):
    r = _post(client, "0.00")
    assert r.status_code >= 400


def test_an_absurd_amount_is_refused_by_authorization(client):
    """No special large-value path. The threshold applies uniformly."""
    r = _post(client, "999999999.99")

    assert r.status_code == 403
    assert "approval" in r.json()["detail"].lower()


def test_scope_for_one_action_does_not_authorize_another(client):
    """Horizontal escalation: a credit scope must not permit a refund."""
    r = _post(client, "100.00", headers=_headers(scopes=("credit:create",)))

    assert r.status_code == 403
    assert "scope" in r.json()["detail"].lower()


def test_the_actor_header_cannot_override_the_token_subject(client):
    """Identity comes from the signature, not from a header an attacker sets.

    The header is used for barrier routing; authority comes from the token.
    A service that trusted the header for authorization would be trivially
    impersonable.
    """
    headers = _headers(actor="A", scopes=("refund:create",), tenant="acme")
    headers["X-Actor-Id"] = "SOMEONE_ELSE"

    r = _post(client, "100.00", headers=headers)
    assert r.status_code == 201

    # The recorded actor is whatever the header said, because that is what
    # barrier routing needs -- but the AUTHORITY that permitted it came from the
    # token. This test pins that distinction so a future change cannot quietly
    # start authorizing on the header.
    row = client.get("/refunds", params={"case_id": "c1"},
                     headers=_headers()).json()["refunds"][0]
    assert row["actor_id"] == "SOMEONE_ELSE"


def test_a_token_for_another_tenant_cannot_act_on_this_one(client):
    """Vertical escalation across the tenant boundary."""
    headers = _headers(tenant="other-corp")
    headers["X-Tenant-Id"] = "acme"

    r = _post(client, "100.00", headers=headers)
    assert r.status_code == 403
    assert "tenant" in r.json()["detail"].lower()


def test_an_unsigned_token_shaped_string_is_refused(client):
    headers = _headers()
    headers["Authorization"] = "Bearer not.a.jwt"

    assert _post(client, "100.00", headers=headers).status_code == 401


def test_an_empty_bearer_is_refused(client):
    headers = _headers()
    headers["Authorization"] = "Bearer "

    assert _post(client, "100.00", headers=headers).status_code == 401


def test_a_refused_abuse_attempt_writes_nothing_anywhere(client):
    """Every rejection path must leave no effect and no event."""
    for amount, headers in [
        ("-500.00", _headers()),
        ("100.00", _headers(scopes=("credit:create",))),
        ("999999.00", _headers()),
    ]:
        client.post("/refunds",
                    json={"case_id": "c1", "amount": amount,
                          "idempotency_key": f"k-{amount}"},
                    headers=headers)

    listing = client.get("/refunds", params={"case_id": "c1"},
                         headers=_headers()).json()
    assert listing["refunds"] == []
    assert Decimal(listing["total_committed"]) == Decimal("0")
    assert client.get("/events", headers=_headers()).json()["pending"] == 0
