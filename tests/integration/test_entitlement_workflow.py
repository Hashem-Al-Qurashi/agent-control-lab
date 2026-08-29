"""Stage 5: E1 breaks the same way the compensation ceiling does.

Two independently-owned systems. Billing owns the plan; Entitlements owns the
grants. Neither can evaluate "every granted feature is permitted by the current
plan" alone.

No sums. No money. Set membership. If the failure appears here too, the result
was never about arithmetic -- it is about an authority owning a fact and a second
system acting on a copy of it.
"""

import pytest
from fastapi.testclient import TestClient

from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from apps.billing.main import app as billing_app
from apps.entitlements.db import run_migrations as ent_migrations
from apps.entitlements.db import truncate_all as ent_truncate
from apps.entitlements.main import app as ent_app
from oracle.entitlements import EntitlementVerdict, evaluate_entitlements

HEADERS = {"X-Actor-Id": "A", "X-Schedule-Id": "S7"}


@pytest.fixture()
def clients(monkeypatch):
    monkeypatch.setenv("BARRIER_ENABLED", "0")
    monkeypatch.setenv("ACL_ENFORCE_POLICY", "0")
    billing_migrations()
    ent_migrations()
    billing_truncate()
    ent_truncate()
    with TestClient(billing_app) as b, TestClient(ent_app) as e:
        yield b, e
    billing_truncate()
    ent_truncate()


def _set_plan(billing, plan, key):
    return billing.post("/plans", json={"case_id": "c1", "plan": plan,
                                        "idempotency_key": key}, headers=HEADERS)


def _grant(ent, feature, key):
    return ent.post("/features", json={"case_id": "c1", "feature": feature,
                                       "idempotency_key": key}, headers=HEADERS)


def _evaluate(billing, ent):
    plan = billing.get("/plans", params={"case_id": "c1"},
                       headers=HEADERS).json()["plan"]
    granted = set(ent.get("/features", params={"case_id": "c1"},
                          headers=HEADERS).json()["granted"])
    return evaluate_entitlements(plan=plan, granted=granted)


def test_a_grant_within_the_plan_is_clean(clients):
    billing, ent = clients
    _set_plan(billing, "PRO", "p1")
    _grant(ent, "sso", "g1")

    assert _evaluate(billing, ent).verdict is EntitlementVerdict.CLEAN


def test_a_downgrade_strands_a_grant_the_new_plan_forbids(clients):
    """The non-monetary analogue of the compensation breach.

    PRO permits sso. After a downgrade to BASIC it does not -- and the grant is
    still there. Neither service is wrong on its own: Billing recorded a valid
    plan change, Entitlements holds a grant that was valid when made.
    """
    billing, ent = clients
    _set_plan(billing, "PRO", "p1")
    _grant(ent, "sso", "g1")
    _set_plan(billing, "BASIC", "p2")

    result = _evaluate(billing, ent)

    assert result.verdict is EntitlementVerdict.VIOLATION
    assert result.unpermitted == {"sso"}


def test_each_service_looks_correct_in_isolation(clients):
    """Why no single service can catch this.

    Billing's plan history is valid. Entitlements' grants are all well-formed.
    The breach exists only in the relationship between them.
    """
    billing, ent = clients
    _set_plan(billing, "PRO", "p1")
    _grant(ent, "sso", "g1")
    _set_plan(billing, "BASIC", "p2")

    assert billing.get("/plans", params={"case_id": "c1"},
                       headers=HEADERS).json()["plan"] == "BASIC"

    grants = ent.get("/features", params={"case_id": "c1"},
                     headers=HEADERS).json()
    assert all(g["state"] == "GRANTED" for g in grants["grants"])
    assert grants["granted"] == ["sso"]


def test_the_grant_is_idempotent(clients):
    billing, ent = clients
    _set_plan(billing, "PRO", "p1")
    first = _grant(ent, "sso", "g1")
    second = _grant(ent, "sso", "g1")

    assert first.status_code == 201
    assert second.status_code == 200
    assert len(ent.get("/features", params={"case_id": "c1"},
                       headers=HEADERS).json()["grants"]) == 1


def test_no_plan_makes_every_grant_unpermitted(clients):
    """Fail closed. A missing plan must not authorise everything."""
    _, ent = clients
    billing, _ = clients
    _grant(ent, "reports", "g1")

    result = _evaluate(billing, ent)
    assert result.verdict is EntitlementVerdict.VIOLATION
