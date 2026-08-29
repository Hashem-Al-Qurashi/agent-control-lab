"""Task 8: Ledger service -- credits.

Mirrors Billing deliberately. The two services are structurally identical and
independently owned; that symmetry is what makes the aggregate invariant span a
boundary neither of them can see.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.ledger.db import connect, run_migrations, truncate_all
from apps.ledger.main import app

HEADERS = {"X-Actor-Id": "B", "X-Schedule-Id": "P1"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BARRIER_ENABLED", "0")
    run_migrations()
    truncate_all()
    with TestClient(app) as c:
        yield c
    truncate_all()


def _post_credit(client, amount, key, case_id="case-1"):
    return client.post(
        "/credits",
        json={"case_id": case_id, "amount": str(amount), "idempotency_key": key},
        headers=HEADERS,
    )


def test_credit_is_created_in_committed_state(client):
    r = _post_credit(client, "500.00", "k1")
    assert r.status_code == 201
    assert r.json()["state"] == "COMMITTED"
    assert r.json()["actor_id"] == "B"


def test_same_idempotency_key_creates_exactly_one_row(client):
    first = _post_credit(client, "500.00", "k1")
    second = _post_credit(client, "500.00", "k1")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    listing = client.get("/credits", params={"case_id": "case-1"}, headers=HEADERS)
    assert len(listing.json()["credits"]) == 1


def test_money_round_trips_as_decimal_without_float_error(client):
    _post_credit(client, "0.10", "k1")
    _post_credit(client, "0.20", "k2")
    listing = client.get("/credits", params={"case_id": "case-1"}, headers=HEADERS)
    assert Decimal(listing.json()["total_committed"]) == Decimal("0.30")


def test_voided_credit_is_excluded_from_the_committed_total(client):
    created = _post_credit(client, "500.00", "k1").json()
    _post_credit(client, "300.00", "k2")

    client.post(f"/credits/{created['id']}/void", headers=HEADERS)

    listing = client.get("/credits", params={"case_id": "case-1"}, headers=HEADERS)
    assert Decimal(listing.json()["total_committed"]) == Decimal("300.00")


def test_unlabelled_request_is_rejected(client):
    r = client.post(
        "/credits",
        json={"case_id": "case-1", "amount": "1.00", "idempotency_key": "k1"},
    )
    assert r.status_code == 400


def test_ledger_connects_to_its_own_database_not_billings(client):
    """The two services must never share a database. One typo invalidates all results."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select current_database()")
        assert cur.fetchone()[0] == "ledger"


def test_ledger_and_billing_are_genuinely_separate_databases(client):
    """A row in one must be invisible to the other -- no shared transaction boundary."""
    from apps.billing.db import connect as billing_connect
    from apps.billing.db import run_migrations as billing_migrations

    billing_migrations()
    _post_credit(client, "500.00", "k1")

    with billing_connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('public.credits') IS NOT NULL AS has_credits"
        )
        assert cur.fetchone()[0] is False, (
            "billing can see the credits table -- the services share a database "
            "and the entire experiment would be an artifact"
        )
