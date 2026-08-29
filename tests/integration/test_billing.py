"""Task 7: Billing service -- refunds, idempotency, Decimal money.

Checkpoints are exercised in the schedule tests. Here the barrier is explicitly
disabled so the domain behaviour is tested on its own. Disabling is by explicit
configuration, never a silent fallback: a checkpoint that quietly no-ops when it
cannot reach the coordinator would fail open, and the entire barrier design is
fail-closed.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.billing.main import app
from apps.billing.db import connect, run_migrations, truncate_all

HEADERS = {"X-Actor-Id": "A", "X-Schedule-Id": "P1"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BARRIER_ENABLED", "0")
    run_migrations()
    truncate_all()
    with TestClient(app) as c:
        yield c
    truncate_all()


def _post_refund(client, amount, key, case_id="case-1"):
    return client.post(
        "/refunds",
        json={
            "case_id": case_id,
            "amount": str(amount),
            "idempotency_key": key,
        },
        headers=HEADERS,
    )


def test_refund_is_created_in_committed_state(client):
    r = _post_refund(client, "600.00", "k1")
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "COMMITTED"
    assert body["amount"] == "600.00"
    assert body["actor_id"] == "A"


def test_same_idempotency_key_creates_exactly_one_row(client):
    first = _post_refund(client, "600.00", "k1")
    second = _post_refund(client, "600.00", "k1")

    assert first.status_code == 201
    assert second.status_code == 200  # replayed, not created
    assert first.json()["id"] == second.json()["id"]

    listing = client.get("/refunds", params={"case_id": "case-1"}, headers=HEADERS)
    assert len(listing.json()["refunds"]) == 1


def test_money_round_trips_as_decimal_without_float_error(client):
    """0.10 + 0.20 must equal 0.30 through the full HTTP + Postgres path."""
    _post_refund(client, "0.10", "k1")
    _post_refund(client, "0.20", "k2")

    listing = client.get("/refunds", params={"case_id": "case-1"}, headers=HEADERS)
    total = Decimal(listing.json()["total_committed"])

    assert total == Decimal("0.30")
    assert str(total) == "0.30"


def test_voided_refund_is_excluded_from_the_committed_total(client):
    created = _post_refund(client, "600.00", "k1").json()
    _post_refund(client, "500.00", "k2")

    void = client.post(f"/refunds/{created['id']}/void", headers=HEADERS)
    assert void.status_code == 200
    assert void.json()["state"] == "VOIDED"

    listing = client.get("/refunds", params={"case_id": "case-1"}, headers=HEADERS)
    assert Decimal(listing.json()["total_committed"]) == Decimal("500.00")


def test_listing_is_scoped_to_the_case(client):
    _post_refund(client, "600.00", "k1", case_id="case-1")
    _post_refund(client, "500.00", "k2", case_id="case-2")

    listing = client.get("/refunds", params={"case_id": "case-1"}, headers=HEADERS)
    assert Decimal(listing.json()["total_committed"]) == Decimal("600.00")


def test_unlabelled_request_is_rejected(client):
    r = client.post(
        "/refunds",
        json={"case_id": "case-1", "amount": "1.00", "idempotency_key": "k1"},
    )
    assert r.status_code == 400


def test_amount_is_stored_with_two_decimal_places(client):
    _post_refund(client, "123.456", "k1")
    listing = client.get("/refunds", params={"case_id": "case-1"}, headers=HEADERS)
    # NUMERIC(12,2) -- the database, not the application, is the authority here.
    assert listing.json()["refunds"][0]["amount"] == "123.46"


def _decision_log(case_id="case-1"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT sequence, actor_id, service, from_state, to_state, amount "
            "FROM decision_log WHERE case_id = %s ORDER BY sequence",
            (case_id,),
        )
        return cur.fetchall()


def test_decision_log_records_every_state_transition(client):
    """The append-only log is load-bearing for later modes that have no
    quiescence point. History cannot be reconstructed from mutable rows, so a
    missing append is unrecoverable rather than merely inconvenient."""
    created = _post_refund(client, "600.00", "k1").json()
    client.post(f"/refunds/{created['id']}/void", headers=HEADERS)

    rows = _decision_log()
    assert [(r[0], r[3], r[4]) for r in rows] == [
        (1, None, "COMMITTED"),
        (2, "COMMITTED", "VOIDED"),
    ]
    assert all(r[1] == "A" and r[2] == "billing" for r in rows)
    assert rows[0][5] == Decimal("600.00")


def test_idempotent_replay_does_not_append_a_second_decision(client):
    """One logical operation, one economic effect, one log entry."""
    _post_refund(client, "600.00", "k1")
    _post_refund(client, "600.00", "k1")

    assert len(_decision_log()) == 1


def test_billing_connects_to_its_own_database_not_the_ledgers(client):
    """One config typo pointing both services at one database invalidates all results."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select current_database()")
        assert cur.fetchone()[0] == "billing"
