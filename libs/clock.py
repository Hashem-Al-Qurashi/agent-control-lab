"""Injectable time.

Bounded-time invariants are the fifth class in docs/INVARIANT-CATALOG.md and the
one the lab did not demonstrate: reservations had no expiry and approvals had no
validity window. Building those needs a clock the tests can control, because an
expiry test that sleeps is slow, flaky, and proves less than it looks like --
it shows something happened after an interval, not that the code consulted a
deadline.

Every bounded-time control here takes a Clock. `tests/unit/test_clock.py`
enforces that nothing under apps/ or libs/ reads the wall clock without a
recorded exemption.
"""

from __future__ import annotations

import datetime
from typing import Protocol, runtime_checkable

UTC = datetime.timezone.utc

# Arbitrary but fixed, so a frozen-clock failure reports a recognisable instant
# rather than "whenever the suite happened to run".
EPOCH = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime.datetime: ...


class SystemClock:
    """Real time, always timezone-aware.

    Aware rather than naive because comparing a naive datetime to an aware one
    raises -- and it would raise in the expiry path, in production, under load.
    """

    def now(self) -> datetime.datetime:
        return datetime.datetime.now(UTC)


class FrozenClock:
    """Time that moves only when a test says so."""

    def __init__(self, at: datetime.datetime | None = None) -> None:
        self._at = at or EPOCH

    def now(self) -> datetime.datetime:
        return self._at

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            # A test that rewinds is asserting something the system never sees.
            raise ValueError("time does not move backwards")
        self._at = self._at + datetime.timedelta(seconds=seconds)
