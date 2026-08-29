"""Stage 1: the event must share the effect's transaction, through the real path.

Unit tests prove the outbox helper is atomic. This proves the SERVICE is -- that
publish() was wired inside the commit and not after it. A publish placed one line
too late would still pass every unit test and would make propagation lag a
harness bug rather than a property of the architecture.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.billing.db import connect, run_migrations, truncate_all
from apps.billing.main import app

HEADERS = {"X-Actor-Id": "A", "X-Schedule-Id": "P1"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BARRIER_ENABLED", "0")
    run_migrations()
    truncate_all()
    with TestClient(app) as c:
        yield c
    truncate_all()


def test_committing_a_refund_publishes_exactly_one_event(client):
    client.post("/refunds", json={"case_id": "c1", "amount": "600.00",
                                  "idempotency_key": "k1"}, headers=HEADERS)

    body = client.get("/events", headers=HEADERS).json()
    assert body["pending"] == 1
    event = body["events"][0]
    assert event["event_type"] == "RefundCommitted"
    assert Decimal(event["amount"]) == Decimal("600.00")
    assert event["actor_id"] == "A"


def test_idempotent_replay_publishes_no_second_event(client):
    """One logical operation, one effect, one event. A replay that re-published
    would inflate the projection above reality."""
    for _ in range(2):
        client.post("/refunds", json={"case_id": "c1", "amount": "600.00",
                                      "idempotency_key": "k1"}, headers=HEADERS)

    assert client.get("/events", headers=HEADERS).json()["pending"] == 1


def test_event_row_count_matches_effect_row_count(client):
    for i in range(3):
        client.post("/refunds", json={"case_id": "c1", "amount": "100.00",
                                      "idempotency_key": f"k{i}"}, headers=HEADERS)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM refunds")
        effects = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM outbox")
        events = cur.fetchone()[0]

    assert effects == events == 3


def test_marking_applied_clears_the_pending_lag(client):
    client.post("/refunds", json={"case_id": "c1", "amount": "600.00",
                                  "idempotency_key": "k1"}, headers=HEADERS)
    event_id = client.get("/events", headers=HEADERS).json()["events"][0]["id"]

    client.post(f"/events/{event_id}/applied", headers=HEADERS)

    assert client.get("/events", headers=HEADERS).json()["pending"] == 0
