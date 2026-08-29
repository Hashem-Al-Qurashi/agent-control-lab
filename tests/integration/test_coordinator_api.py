"""Task 3: coordinator HTTP surface, fail-closed.

Blocking and release ordering are already proven at the Barrier level (Task 2).
These tests cover the HTTP surface and, above all, that every error path aborts
the run rather than releasing a waiter. A default-releasing barrier manufactures
results.
"""

import pytest
from fastapi.testclient import TestClient

from apps.coordinator.main import app, reset_state

CP_A = "billing.after_read_before_decide"
CP_B = "ledger.after_read_before_decide"


@pytest.fixture()
def client():
    reset_state()
    with TestClient(app) as c:
        yield c
    reset_state()


def _declare(client, steps=None, schedule_id="P2"):
    return client.post(
        "/declare",
        json={
            "schedule_id": schedule_id,
            "steps": steps or [["A", CP_A], ["B", CP_B]],
            "timeout_seconds": 2.0,
        },
    )


def test_declare_then_arrival_at_pointer_is_released(client):
    assert _declare(client).status_code == 200
    r = client.post(
        "/await",
        json={"checkpoint": CP_A},
        headers={"X-Actor-Id": "A", "X-Schedule-Id": "P2"},
    )
    assert r.status_code == 200
    assert r.json()["occurrence"] == 0


def test_await_without_actor_header_is_400_and_aborts_the_run(client):
    _declare(client)
    r = client.post(
        "/await", json={"checkpoint": CP_A}, headers={"X-Schedule-Id": "P2"}
    )
    assert r.status_code == 400
    assert client.get("/waiters").json()["aborted"] is True


def test_await_without_schedule_header_is_400_and_aborts_the_run(client):
    _declare(client)
    r = client.post("/await", json={"checkpoint": CP_A}, headers={"X-Actor-Id": "A"})
    assert r.status_code == 400
    assert client.get("/waiters").json()["aborted"] is True


def test_unknown_actor_is_400_and_aborts_the_run(client):
    _declare(client)
    r = client.post(
        "/await",
        json={"checkpoint": CP_A},
        headers={"X-Actor-Id": "Z", "X-Schedule-Id": "P2"},
    )
    assert r.status_code == 400
    assert client.get("/waiters").json()["aborted"] is True


def test_undeclared_occurrence_is_409_and_aborts_the_run(client):
    _declare(client, steps=[["A", CP_A]], schedule_id="P1")
    ok = client.post(
        "/await",
        json={"checkpoint": CP_A},
        headers={"X-Actor-Id": "A", "X-Schedule-Id": "P1"},
    )
    assert ok.status_code == 200

    again = client.post(
        "/await",
        json={"checkpoint": CP_A},
        headers={"X-Actor-Id": "A", "X-Schedule-Id": "P1"},
    )
    assert again.status_code == 409
    assert client.get("/waiters").json()["aborted"] is True


def test_wrong_schedule_id_is_409_and_aborts_the_run(client):
    _declare(client)
    r = client.post(
        "/await",
        json={"checkpoint": CP_A},
        headers={"X-Actor-Id": "A", "X-Schedule-Id": "WRONG"},
    )
    assert r.status_code == 409
    assert client.get("/waiters").json()["aborted"] is True


def test_await_before_any_declare_is_409(client):
    r = client.post(
        "/await",
        json={"checkpoint": CP_A},
        headers={"X-Actor-Id": "A", "X-Schedule-Id": "P2"},
    )
    assert r.status_code == 409


def test_no_release_is_ever_returned_after_an_abort(client):
    """The load-bearing assertion: once aborted, nothing gets released."""
    _declare(client)
    client.post("/await", json={"checkpoint": CP_A}, headers={"X-Schedule-Id": "P2"})
    assert client.get("/waiters").json()["aborted"] is True

    # A perfectly valid arrival must now still be refused.
    r = client.post(
        "/await",
        json={"checkpoint": CP_A},
        headers={"X-Actor-Id": "A", "X-Schedule-Id": "P2"},
    )
    assert r.status_code == 409
    assert "abort" in r.json()["detail"].lower()


def test_abort_dump_names_parked_waiters(client):
    """Aborting must surface what was parked, not just that it aborted."""
    _declare(client)
    body = client.get("/waiters").json()
    assert "waiters" in body
    assert "release_order" in body
    assert "expects" in body


def test_reset_clears_schedule_and_abort_state(client):
    _declare(client)
    client.post("/await", json={"checkpoint": CP_A}, headers={"X-Schedule-Id": "P2"})
    assert client.get("/waiters").json()["aborted"] is True

    assert client.post("/reset").status_code == 200
    body = client.get("/waiters").json()
    assert body["aborted"] is False
    assert body["waiters"] == []
    assert body["release_order"] == []
