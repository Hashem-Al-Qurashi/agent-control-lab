"""Task 4: leases and heartbeats for parked waiters.

With agents in separate OS processes, a dead agent parked at a barrier hangs the
suite forever -- with threads it would raise. A timeout alone is not enough: it
cannot distinguish a dead actor from a slow one, and picking a timeout long
enough for the slow case makes the dead case cost that full timeout on every
run.

A lease makes death observable. The clock is injectable so these tests are
deterministic rather than sleep-based -- a determinism harness whose own tests
depend on wall-clock timing would be self-undermining.
"""

import threading
import time

from apps.coordinator.barrier import Barrier, BarrierAborted
from apps.coordinator.schedule import Schedule

CP_A = "billing.after_read_before_decide"
CP_B = "ledger.after_read_before_decide"


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self._now = now

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _park(barrier, actor, checkpoint, outcome, timeout=5.0):
    def run():
        try:
            barrier.wait(actor, checkpoint, timeout=timeout, lease_ttl=10.0)
            outcome.append("released")
        except BarrierAborted:
            outcome.append("aborted")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_parked_waiter_registers_a_lease():
    clock = FakeClock()
    barrier = Barrier(Schedule("P2", [("A", CP_A), ("B", CP_B)]), clock=clock)
    outcome: list[str] = []

    t = _park(barrier, "B", CP_B, outcome)
    time.sleep(0.1)

    assert barrier.leases() == {("B", CP_B, 0): 1010.0}
    barrier.abort("cleanup")
    t.join(timeout=5.0)


def test_expired_lease_is_reaped_and_aborts_the_run():
    clock = FakeClock()
    barrier = Barrier(Schedule("P2", [("A", CP_A), ("B", CP_B)]), clock=clock)
    outcome: list[str] = []

    t = _park(barrier, "B", CP_B, outcome)
    time.sleep(0.1)

    clock.advance(11.0)
    expired = barrier.reap()

    assert expired == [("B", CP_B, 0)]
    t.join(timeout=5.0)
    assert outcome == ["aborted"]
    assert barrier.aborted is not None
    assert "lease expired" in barrier.aborted
    assert barrier.release_order() == []


def test_heartbeat_refreshes_the_lease_so_reap_is_a_noop():
    clock = FakeClock()
    barrier = Barrier(Schedule("P2", [("A", CP_A), ("B", CP_B)]), clock=clock)
    outcome: list[str] = []

    t = _park(barrier, "B", CP_B, outcome)
    time.sleep(0.1)

    clock.advance(9.0)
    assert barrier.heartbeat("B", CP_B, 0) is True

    clock.advance(5.0)  # 14s since park, but only 5s since heartbeat
    assert barrier.reap() == []
    assert barrier.aborted is None

    barrier.abort("cleanup")
    t.join(timeout=5.0)


def test_heartbeat_for_unknown_waiter_returns_false():
    clock = FakeClock()
    barrier = Barrier(Schedule("P2", [("A", CP_A), ("B", CP_B)]), clock=clock)

    assert barrier.heartbeat("B", CP_B, 0) is False


def test_reap_with_no_parked_waiters_is_a_noop():
    clock = FakeClock()
    barrier = Barrier(Schedule("P1", [("A", CP_A)]), clock=clock)

    clock.advance(1000.0)
    assert barrier.reap() == []
    assert barrier.aborted is None


def test_released_waiter_lease_is_dropped():
    """A lease must not outlive the waiter it belongs to."""
    clock = FakeClock()
    barrier = Barrier(Schedule("P2", [("A", CP_A), ("B", CP_B)]), clock=clock)
    outcome: list[str] = []

    t = _park(barrier, "B", CP_B, outcome)
    time.sleep(0.1)
    barrier.wait("A", CP_A, timeout=5.0, lease_ttl=10.0)
    t.join(timeout=5.0)

    assert outcome == ["released"]
    assert barrier.leases() == {}

    clock.advance(1000.0)
    assert barrier.reap() == []
    assert barrier.aborted is None


def test_reaper_thread_aborts_a_dead_waiter_without_manual_reap():
    """End-to-end: the coordinator must not require anyone to call reap()."""
    from apps.coordinator.barrier import Reaper

    clock = FakeClock()
    barrier = Barrier(Schedule("P2", [("A", CP_A), ("B", CP_B)]), clock=clock)
    outcome: list[str] = []

    t = _park(barrier, "B", CP_B, outcome)
    time.sleep(0.1)

    reaper = Reaper(barrier, interval=0.01)
    reaper.start()
    try:
        clock.advance(11.0)
        t.join(timeout=5.0)
    finally:
        reaper.stop()

    assert outcome == ["aborted"]
    assert "lease expired" in (barrier.aborted or "")
