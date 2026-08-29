"""Stage 1: the service enforces policy; the agent never does.

A policy module that is never called authorizes nothing. Until the service
consults it, "properly authorized" is a claim about a file rather than about the
system, and the Stage 1 sentence -- the failure occurred DESPITE proper
authorization -- would be false.

The enforcement point is the service, deliberately. An actor that evaluates its
own permissions has no permissions, whether that actor is an LLM or a
deterministic policy.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.billing.db import run_migrations, truncate_all
from apps.billing.main import app
from libs.identity import issue_token


def _headers(actor="A", scopes=("refund:create",), tenant="acme"):
    return {
        "X-Actor-Id": actor,
        "X-Schedule-Id": "S1",
        "Authorization": f"Bearer {issue_token(actor, list(scopes), tenant)}",
        "X-Tenant-Id": tenant,
    }


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BARRIER_ENABLED", "0")
    monkeypatch.setenv("ACL_ENFORCE_POLICY", "1")
    run_migrations()
    truncate_all()
    with TestClient(app) as c:
        yield c
    truncate_all()


def _post(client, headers, amount="100.00", key="k1"):
    return client.post(
        "/refunds",
        json={"case_id": "c1", "amount": amount, "idempotency_key": key},
        headers=headers,
    )


def test_an_authorized_action_within_authority_succeeds(client):
    assert _post(client, _headers(), amount="500.00").status_code == 201


def test_a_missing_token_is_rejected(client):
    headers = _headers()
    del headers["Authorization"]

    assert _post(client, headers).status_code == 401


def test_a_forged_token_is_rejected(client):
    headers = _headers()
    headers["Authorization"] = headers["Authorization"][:-4] + "AAAA"

    assert _post(client, headers).status_code == 401


def test_a_missing_scope_is_rejected(client):
    assert _post(client, _headers(scopes=("invoice:read",))).status_code == 403


def test_a_cross_tenant_action_is_rejected(client):
    headers = _headers(tenant="acme")
    headers["X-Tenant-Id"] = "other-corp"

    r = _post(client, headers)
    assert r.status_code == 403
    assert "tenant" in r.json()["detail"].lower()


def test_above_threshold_without_approval_authority_is_rejected(client):
    r = _post(client, _headers(), amount="500.01")

    assert r.status_code == 403
    assert "approval" in r.json()["detail"].lower()


def test_above_threshold_with_approval_authority_succeeds(client):
    headers = _headers(scopes=("refund:create", "refund:approved"))

    assert _post(client, headers, amount="900.00").status_code == 201


def test_a_rejected_action_leaves_no_effect_and_no_event(client):
    """A denied action must not be half-done. No row, no outbox entry."""
    _post(client, _headers(scopes=("invoice:read",)), amount="600.00")

    listing = client.get("/refunds", params={"case_id": "c1"},
                         headers=_headers()).json()
    assert listing["refunds"] == []
    assert Decimal(listing["total_committed"]) == Decimal("0")

    events = client.get("/events", headers=_headers()).json()
    assert events["pending"] == 0


def test_enforcement_is_off_unless_explicitly_enabled(monkeypatch):
    """Stage 0 schedules predate the policy and must keep working.

    Enforcement is opt-in configuration, never a silent default -- the same rule
    the barrier follows.
    """
    monkeypatch.setenv("BARRIER_ENABLED", "0")
    monkeypatch.setenv("ACL_ENFORCE_POLICY", "0")
    run_migrations()
    truncate_all()
    with TestClient(app) as c:
        r = c.post(
            "/refunds",
            json={"case_id": "c1", "amount": "600.00", "idempotency_key": "k1"},
            headers={"X-Actor-Id": "A", "X-Schedule-Id": "P1"},
        )
    truncate_all()
    assert r.status_code == 201
