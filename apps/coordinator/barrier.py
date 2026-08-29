"""Deterministic barrier: parks arrivals until the schedule pointer reaches them.

Blocking is a real threading.Event. A poll loop would add scheduler jitter after
release, producing non-reproducible ordering that masquerades as the interesting
race -- and non-reproducible ordering invalidates the whole method.

Fails closed. Every error path aborts rather than releasing. A default-releasing
barrier manufactures results.

Parked waiters hold a lease. With agents in separate OS processes a dead agent
would otherwise hang the suite until timeout, and a timeout alone cannot tell a
dead actor from a slow one. The clock is injectable so lease behaviour can be
tested deterministically rather than by sleeping.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from apps.coordinator.schedule import Schedule

Key = tuple[str, str, int]


class BarrierTimeout(Exception):
    """A waiter was never released. Carries a dump of everything still parked.

    Without this, every failure mode presents as a hang rather than a diagnosis.
    """


class BarrierAborted(Exception):
    """The run was aborted. Parked waiters are woken but never released.

    Waking a parked waiter on abort is not the same as releasing it -- the
    distinction is the whole point of failing closed.
    """


class Barrier:
    def __init__(
        self,
        schedule: Schedule,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._schedule = schedule
        self._clock = clock
        self._lock = threading.Lock()
        self._parked: dict[Key, threading.Event] = {}
        self._leases: dict[Key, float] = {}  # key -> expiry
        self._lease_ttls: dict[Key, float] = {}  # key -> ttl it was granted with
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
            self._leases.clear()
            self._lease_ttls.clear()
        for event in parked:
            event.set()

    def wait(
        self,
        actor_id: str,
        checkpoint: str,
        timeout: float | None = None,
        lease_ttl: float | None = None,
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
            if lease_ttl is not None:
                self._leases[key] = self._clock() + lease_ttl
                self._lease_ttls[key] = lease_ttl

        if not event.wait(timeout):
            with self._lock:
                self._parked.pop(key, None)
                self._leases.pop(key, None)
                self._lease_ttls.pop(key, None)
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

    def heartbeat(self, actor_id: str, checkpoint: str, occurrence: int) -> bool:
        """Refresh a parked waiter's lease. False if it holds no lease."""
        key: Key = (actor_id, checkpoint, occurrence)
        with self._lock:
            if key not in self._leases:
                return False
            self._leases[key] = self._clock() + self._lease_ttls[key]
            return True

    def reap(self) -> list[Key]:
        """Abort the run if any parked waiter's lease has expired.

        Returns the expired keys. A dead actor becomes an explicit, named
        failure instead of a hang that is indistinguishable from slowness.
        """
        now = self._clock()
        with self._lock:
            expired = sorted(k for k, exp in self._leases.items() if exp <= now)
        if expired:
            self.abort(f"lease expired for {expired}")
        return expired

    def leases(self) -> dict[Key, float]:
        with self._lock:
            return dict(self._leases)

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
        self._leases.pop(key, None)
        self._lease_ttls.pop(key, None)
        self._schedule.advance()

        while True:
            step = self._schedule.current_step
            if step is None:
                return
            event = self._parked.pop(step, None)
            if event is None:
                return
            self._leases.pop(step, None)
            self._lease_ttls.pop(step, None)
            self._release_order.append(step)
            event.set()
            self._schedule.advance()


class Reaper:
    """Background lease reaper, so nothing depends on someone calling reap()."""

    def __init__(self, barrier: Barrier, interval: float = 1.0) -> None:
        self._barrier = barrier
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            if self._barrier.aborted is not None:
                return
            self._barrier.reap()
