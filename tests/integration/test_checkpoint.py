"""Task 6: the checkpoint() call a service makes from inside a handler.

Exercised against a live coordinator over a real socket, because the whole point
of a checkpoint is that it blocks. A test that never actually blocks would prove
nothing about the mechanism every downstream result depends on.
"""

import threading
import time

import httpx
import pytest

from libs.barrier.client import BarrierClient, CheckpointError
from libs.barrier.middleware import MissingActorIdentity, actor_identity

CP_A = "billing.after_read_before_decide"
CP_B = "ledger.after_read_before_decide"


def _declare(url, steps, schedule_id="P2", timeout=10.0):
    r = httpx.post(
        f"{url}/declare",
        json={
            "schedule_id": schedule_id,
            "steps": steps,
            "timeout_seconds": timeout,
            "lease_ttl_seconds": 30.0,
        },
        timeout=5.0,
    )
    r.raise_for_status()


def test_checkpoint_at_pointer_returns_immediately(clean_coordinator):
    url = clean_coordinator
    _declare(url, [["A", CP_A]], schedule_id="P1")
    client = BarrierClient(url)

    with actor_identity("A", "P1"):
        occurrence = client.checkpoint(CP_A)

    assert occurrence == 0


def test_checkpoint_blocks_until_released(clean_coordinator):
    """The load-bearing assertion: it blocks for a real wall-clock interval."""
    url = clean_coordinator
    _declare(url, [["A", CP_A], ["B", CP_B]])
    client = BarrierClient(url)

    elapsed: list[float] = []
    started = threading.Event()

    def park_b():
        with actor_identity("B", "P2"):
            started.set()
            t0 = time.monotonic()
            client.checkpoint(CP_B)
            elapsed.append(time.monotonic() - t0)

    t = threading.Thread(target=park_b, daemon=True)
    t.start()
    assert started.wait(5.0)

    hold = 0.4
    time.sleep(hold)
    with actor_identity("A", "P2"):
        client.checkpoint(CP_A)

    t.join(timeout=10.0)
    assert elapsed, "parked checkpoint never returned"
    assert elapsed[0] >= hold, (
        f"checkpoint returned after {elapsed[0]:.3f}s but was held {hold}s -- "
        "it did not actually block"
    )


def test_checkpoint_without_actor_identity_raises(clean_coordinator):
    """A checkpoint cannot invent an actor. It must fail rather than guess."""
    client = BarrierClient(clean_coordinator)
    with pytest.raises(MissingActorIdentity):
        client.checkpoint(CP_A)


def test_checkpoint_surfaces_an_aborted_run(clean_coordinator):
    url = clean_coordinator
    _declare(url, [["A", CP_A]], schedule_id="P1")
    httpx.post(
        f"{url}/await",
        json={"checkpoint": CP_A},
        headers={"X-Schedule-Id": "P1"},  # no actor -> aborts the run
        timeout=5.0,
    )
    client = BarrierClient(url)

    with actor_identity("A", "P1"):
        with pytest.raises(CheckpointError) as exc:
            client.checkpoint(CP_A)
    assert "abort" in str(exc.value).lower()


def test_checkpoint_sends_the_bound_actor_not_a_guess(clean_coordinator):
    url = clean_coordinator
    _declare(url, [["B", CP_B], ["A", CP_A]])
    client = BarrierClient(url)

    with actor_identity("B", "P2"):
        client.checkpoint(CP_B)

    order = httpx.get(f"{url}/waiters", timeout=5.0).json()["release_order"]
    assert order == [["B", CP_B, 0]]
