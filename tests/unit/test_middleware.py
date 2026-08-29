"""Task 5: actor identity is a wire value, bound at the ingress boundary.

A checkpoint cannot derive the actor from the runtime -- PID, thread id, task id
and contextvars all identify the *server's* unit of work, not the caller. Two
actors traverse the same handler on the same server, so identity has to arrive
on the wire and be bound to request scope.

Binding an explicit header to a request-scoped contextvar is correct. Inferring
identity from runtime state is what is forbidden, and the difference matters:
the wrong one fails silently by releasing the wrong actor, which turns a green
run into a fabricated schedule.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from libs.barrier.middleware import (
    ActorContextMiddleware,
    MissingActorIdentity,
    current_actor,
    current_schedule,
    outbound_headers,
)


def _app(strict: bool = True) -> FastAPI:
    app = FastAPI()
    app.add_middleware(ActorContextMiddleware, strict=strict)

    @app.get("/whoami")
    def whoami() -> dict:
        return {"actor": current_actor(), "schedule": current_schedule()}

    @app.get("/outbound")
    def outbound() -> dict:
        return {"headers": outbound_headers()}

    return app


def test_labelled_request_binds_actor_to_request_scope():
    with TestClient(_app()) as c:
        r = c.get("/whoami", headers={"X-Actor-Id": "A", "X-Schedule-Id": "P2"})
    assert r.status_code == 200
    assert r.json() == {"actor": "A", "schedule": "P2"}


def test_unlabelled_request_is_rejected_in_strict_mode():
    with TestClient(_app(strict=True)) as c:
        r = c.get("/whoami")
    assert r.status_code == 400
    assert "X-Actor-Id" in r.json()["detail"]


def test_missing_schedule_header_is_rejected_in_strict_mode():
    with TestClient(_app(strict=True)) as c:
        r = c.get("/whoami", headers={"X-Actor-Id": "A"})
    assert r.status_code == 400
    assert "X-Schedule-Id" in r.json()["detail"]


def test_unlabelled_request_is_allowed_outside_strict_mode():
    with TestClient(_app(strict=False)) as c:
        r = c.get("/whoami")
    assert r.status_code == 200
    assert r.json() == {"actor": None, "schedule": None}


def test_outbound_headers_forward_the_inbound_actor():
    """Any outbound call a service makes must carry the inbound actor id.

    Enforced here rather than left to convention -- a service that calls another
    service without forwarding identity silently detaches the downstream
    checkpoint from the actor that caused it.
    """
    with TestClient(_app()) as c:
        r = c.get("/outbound", headers={"X-Actor-Id": "B", "X-Schedule-Id": "P3"})
    assert r.json()["headers"] == {"X-Actor-Id": "B", "X-Schedule-Id": "P3"}


def test_context_does_not_leak_between_requests():
    app = _app()
    with TestClient(app) as c:
        first = c.get("/whoami", headers={"X-Actor-Id": "A", "X-Schedule-Id": "P2"})
        second = c.get("/whoami", headers={"X-Actor-Id": "B", "X-Schedule-Id": "P2"})
    assert first.json()["actor"] == "A"
    assert second.json()["actor"] == "B"


def test_current_actor_outside_a_request_raises():
    """Reading identity outside a request must fail loudly, not return a stale value."""
    with pytest.raises(MissingActorIdentity):
        outbound_headers()
