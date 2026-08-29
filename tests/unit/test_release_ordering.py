"""Task 2: release ordering proven in isolation.

The barrier's ordering must be unit-tested on its own and never trusted on the
strength of a P2 run. If ordering is wrong, every downstream result is an
artifact of the rig rather than a property of the system.

The blocking primitive must be a real threading.Event. A poll loop introduces
scheduler jitter after release, producing non-reproducible ordering that
masquerades as the interesting race.

Note on what is asserted: the barrier's own release ledger, not the order in
which waiter threads happen to return. A released waiter's Event is set before
the releasing thread returns from wait(), so thread-return order is genuinely
racy and asserting on it would be flaky. The ledger is the contract.
"""

import random
import threading
import time

import pytest

from apps.coordinator.barrier import Barrier, BarrierTimeout
from apps.coordinator.schedule import Schedule

CP_A = "billing.after_read_before_decide"
CP_B = "ledger.after_read_before_decide"
CP_A2 = "billing.after_commit_before_ack"
CP_B2 = "ledger.after_commit_before_ack"


def _run_waiters(barrier, arrivals, timeout=5.0):
    """Start one thread per arrival in the given order; join them all."""
    errors: list[BaseException] = []
    lock = threading.Lock()

    def waiter(actor, checkpoint):
        try:
            barrier.wait(actor, checkpoint, timeout=timeout)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test
            with lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=waiter, args=(actor, cp), daemon=True)
        for actor, cp in arrivals
    ]
    for t in threads:
        t.start()
        # Let each arrival register before the next, so arrival order is the
        # variable under test rather than a thread-start race.
        time.sleep(0.01)
    for t in threads:
        t.join(timeout=timeout + 1)
        assert not t.is_alive(), "waiter thread did not finish"

    assert not errors, f"waiter raised: {errors!r}"


def test_out_of_order_arrival_parks_until_its_turn():
    schedule = Schedule("P2", [("A", CP_A), ("B", CP_B)])
    barrier = Barrier(schedule)

    # B arrives first but A holds the pointer: B must park, not proceed.
    _run_waiters(barrier, [("B", CP_B), ("A", CP_A)])

    assert barrier.release_order() == [("A", CP_A, 0), ("B", CP_B, 0)]


def test_parked_waiter_does_not_proceed_before_its_release():
    """Direct assertion that parking actually blocks."""
    schedule = Schedule("P2", [("A", CP_A), ("B", CP_B)])
    barrier = Barrier(schedule)
    proceeded = threading.Event()

    def parked():
        barrier.wait("B", CP_B, timeout=5.0)
        proceeded.set()

    t = threading.Thread(target=parked, daemon=True)
    t.start()
    time.sleep(0.1)

    assert not proceeded.is_set(), "B proceeded while A still held the pointer"

    barrier.wait("A", CP_A, timeout=5.0)
    assert proceeded.wait(5.0), "B never proceeded after A released"
    t.join(timeout=5.0)


def test_release_order_equals_declared_order_across_randomized_arrivals():
    declared = [("A", CP_A), ("B", CP_B), ("A", CP_A2), ("B", CP_B2)]
    expected = [(actor, cp, 0) for actor, cp in declared]

    for trial in range(100):
        schedule = Schedule(f"P2-{trial}", declared)
        barrier = Barrier(schedule)
        arrivals = declared[:]
        random.shuffle(arrivals)

        _run_waiters(barrier, arrivals)

        assert barrier.release_order() == expected, (
            f"trial {trial}: arrival order {arrivals} produced "
            f"{barrier.release_order()}"
        )


def test_parked_waiter_wakes_promptly_rather_than_by_polling():
    """A poll loop would show wake latency on the order of its interval."""
    schedule = Schedule("P2", [("A", CP_A), ("B", CP_B)])
    barrier = Barrier(schedule)

    woke_at: list[float] = []

    def parked():
        barrier.wait("B", CP_B, timeout=5.0)
        woke_at.append(time.monotonic())

    t = threading.Thread(target=parked, daemon=True)
    t.start()
    time.sleep(0.05)  # ensure B is parked

    released_at = time.monotonic()
    barrier.wait("A", CP_A, timeout=5.0)
    t.join(timeout=5.0)

    assert woke_at, "parked waiter never woke"
    latency = woke_at[0] - released_at
    assert latency < 0.05, f"wake latency {latency:.3f}s suggests a poll loop"


def test_waiter_that_is_never_released_times_out_with_a_dump():
    schedule = Schedule("P2", [("A", CP_A), ("B", CP_B)])
    barrier = Barrier(schedule)

    with pytest.raises(BarrierTimeout) as exc:
        barrier.wait("B", CP_B, timeout=0.2)

    # The dump must name the parked waiter, or every failure presents as a hang.
    assert "B" in str(exc.value)
    assert CP_B in str(exc.value)


def test_completed_schedule_reports_no_parked_waiters():
    schedule = Schedule("P1", [("A", CP_A)])
    barrier = Barrier(schedule)
    barrier.wait("A", CP_A, timeout=5.0)

    assert barrier.waiters() == []
    assert schedule.is_complete
