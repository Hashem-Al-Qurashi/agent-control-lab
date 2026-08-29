"""Stage 2: a reservation must be released when its action does not happen.

A hold that outlives its purpose is not a safety mechanism, it is a leak. The
budget it occupies is invisible -- no refund exists, no credit exists, and yet
legitimate later actions are refused. Worse, the failure looks like the control
working correctly, so nobody investigates.

This is the compensation half of the hardened arm. Reserving is only safe if
un-reserving is guaranteed on the paths where the action does not land.
"""

import httpx
import pytest

from apps.control.db import run_migrations, truncate_all

@pytest.fixture(scope="module")
def control_service():
    import os
    import pathlib
    import signal
    import socket
    import subprocess
    import sys
    import time

    repo = pathlib.Path(__file__).resolve().parents[2]
    run_migrations()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "apps.control.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--workers", "2",
         "--log-level", "error"],
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(repo), "BARRIER_ENABLED": "0"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    headers = {"X-Actor-Id": "T", "X-Schedule-Id": "T"}
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{url}/health", headers=headers, timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:  # pragma: no cover
        proc.send_signal(signal.SIGTERM)
        pytest.fail("control did not start")

    yield url
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=15)


@pytest.fixture(autouse=True)
def clean():
    truncate_all()
    yield
    truncate_all()


def _headers(actor="A"):
    return {"X-Actor-Id": actor, "X-Schedule-Id": "T"}


def _reserve(url, actor, amount, key, case="c1", ceiling="1000.00"):
    return httpx.post(
        f"{url}/reservations",
        json={"case_id": case, "amount": amount, "idempotency_key": key,
              "authorized_compensation": ceiling},
        headers=_headers(actor), timeout=30.0,
    )


def test_a_released_hold_frees_the_budget_it_occupied(control_service, clean):
    """The core of the leak. Without release, B is refused for an action that
    never happened."""
    first = _reserve(control_service, "A", "600.00", "k1")
    assert first.status_code == 201

    released = httpx.post(
        f"{control_service}/reservations/{first.json()['id']}/release",
        headers=_headers("A"), timeout=30.0,
    )
    assert released.status_code == 200
    assert released.json()["state"] == "RELEASED"

    assert _reserve(control_service, "B", "600.00", "k2").status_code == 201


def test_an_unreleased_hold_still_blocks(control_service, clean):
    """The control must actually be doing something, or the test above proves
    nothing."""
    assert _reserve(control_service, "A", "600.00", "k1").status_code == 201
    assert _reserve(control_service, "B", "600.00", "k2").status_code == 409


def test_a_committed_hold_is_not_released(control_service, clean):
    """Committed means the money moved. Releasing it would free budget that is
    genuinely spent."""
    first = _reserve(control_service, "A", "600.00", "k1")
    httpx.post(
        f"{control_service}/reservations/{first.json()['id']}/commit",
        headers=_headers("A"), timeout=30.0,
    )

    assert _reserve(control_service, "B", "600.00", "k2").status_code == 409


def test_releasing_twice_is_idempotent(control_service, clean):
    """Recovery paths run more than once. A second release must not free budget
    a third actor already took."""
    first = _reserve(control_service, "A", "600.00", "k1")
    rid = first.json()["id"]

    for _ in range(2):
        r = httpx.post(f"{control_service}/reservations/{rid}/release",
                       headers=_headers("A"), timeout=30.0)
        assert r.status_code == 200

    assert _reserve(control_service, "B", "1000.00", "k2").status_code == 201


def test_releasing_an_unknown_reservation_is_a_404(control_service, clean):
    r = httpx.post(f"{control_service}/reservations/999999/release",
                   headers=_headers("A"), timeout=30.0)
    assert r.status_code == 404


def test_committing_a_released_hold_is_refused(control_service, clean):
    """A released hold has no budget behind it. Committing it would create
    authority from nothing."""
    first = _reserve(control_service, "A", "600.00", "k1")
    rid = first.json()["id"]
    httpx.post(f"{control_service}/reservations/{rid}/release",
               headers=_headers("A"), timeout=30.0)

    r = httpx.post(f"{control_service}/reservations/{rid}/commit",
                   headers=_headers("A"), timeout=30.0)
    assert r.status_code == 409
