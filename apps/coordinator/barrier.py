"""Deterministic barrier: parks arrivals until the schedule pointer reaches them.

Blocking is a real threading.Event. A poll loop would add scheduler jitter after
release, producing non-reproducible ordering that masquerades as the interesting
race -- and non-reproducible ordering invalidates the whole method.

Fails closed. Every error path aborts rather than releasing. A default-releasing
barrier manufactures results.
"""

from __future__ import annotations

import threading

from apps.coordinator.schedule import Schedule

Key = tuple[str, str, int]


class BarrierTimeout(Exception):
    """A waiter was never released. Carries a dump of everything still parked.

    With agents in separate processes a dead actor parked at a barrier would
    otherwise hang the suite forever, and every failure mode would present as a
    hang rather than a diagnosis.
    """


class BarrierAborted(Exception):
    """The run was aborted. Parked waiters are woken but never released.

    Waking a parked waiter on abort is not the same as releasing it -- the
    distinction is the whole point of failing closed.
    """


class Barrier:
    def __init__(self, schedule: Schedule) -> None:
        self._schedule = schedule
        self._lock = threading.Lock()
        self._parked: dict[Key, threading.Event] = {}
        self._release_order: list[Key] = []
        self._aborted: str | None = None

    @property
    def aborted(self) -> str | None:
        return self._aborted

    def abort(self, reason: str) -> None:
        """Mark the run aborted and wake every parked waiter without releasing."""
        with self._lock:
            if self._aborted is None:
                self._aborted = reason
            parked = list(self._parked.values())
            self._parked.clear()
        for event in parked:
            event.set()

    def wait(
        self, actor_id: str, checkpoint: str, timeout: float | None = None
    ) -> int:
        """Block until this arrival is at the pointer. Returns occurrence index.

        Raises UndeclaredOccurrence (from Schedule) for an unknown actor,
        unknown checkpoint, or an occurrence beyond the declared count.
        Raises BarrierAborted if the run was aborted, BarrierTimeout if the
        release never comes.
        """
        with self._lock:
            if self._aborted is not None:
                raise BarrierAborted(self._aborted)
            occurrence, is_next = self._schedule.arrive(actor_id, checkpoint)
            key: Key = (actor_id, checkpoint, occurrence)
            if is_next:
                self._advance_locked(key)
                return occurrence
            event = threading.Event()
            self._parked[key] = event

        if not event.wait(timeout):
            with self._lock:
                self._parked.pop(key, None)
                dump = self._waiters_locked()
                expected = self._schedule.current_step
            raise BarrierTimeout(
                f"schedule={self._schedule.schedule_id} waiter={key} was never "
                f"released; pointer expects {expected}; still parked: {dump}"
            )

        # Woken. Distinguish an actual release from an abort-wake.
        if self._aborted is not None:
            raise BarrierAborted(self._aborted)
        return occurrence

    def waiters(self) -> list[Key]:
        with self._lock:
            return self._waiters_locked()

    def release_order(self) -> list[Key]:
        """The order in which the barrier actually released waiters.

        This is the contract, not the order in which waiter threads return -- a
        released waiter's Event is set before the releasing thread returns, so
        thread-return order is racy by construction.
        """
        with self._lock:
            return list(self._release_order)

    def _waiters_locked(self) -> list[Key]:
        return sorted(self._parked)

    def _advance_locked(self, key: Key) -> None:
        """Record a release, advance, then cascade through parked waiters."""
        self._release_order.append(key)
        self._schedule.advance()

        while True:
            step = self._schedule.current_step
            if step is None:
                return
            event = self._parked.pop(step, None)
            if event is None:
                return
            self._release_order.append(step)
            event.set()
            self._schedule.advance()
