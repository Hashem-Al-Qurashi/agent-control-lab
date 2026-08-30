"""Time has to be injected, or bounded-time invariants cannot be tested.

An expiry test that sleeps is slow, flaky, and proves less than it appears to:
it demonstrates that something happened after a wall-clock interval, not that
the code consulted a deadline. Every bounded-time control in this repo takes a
clock.
"""

import ast
import datetime
import pathlib

import pytest

from libs.clock import Clock, FrozenClock, SystemClock

REPO = pathlib.Path(__file__).resolve().parents[2]

# Files allowed to read the wall clock directly, each with the reason it is
# allowed. An exemption without a reason is how these lists rot.
EXEMPT = {
    "libs/clock.py": "defines the clock",
    "libs/identity.py": "mints `exp`; expiry VERIFICATION is delegated to PyJWT",
    "libs/request_log.py": "observability timestamps, never a decision",
}

WALL_CLOCK = {"now", "utcnow", "time", "monotonic"}


def test_the_system_clock_returns_an_aware_utc_instant():
    """A naive datetime compared against an aware one raises at runtime, in the
    expiry path, under load -- the worst place to find it."""
    now = SystemClock().now()

    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.timedelta(0)


def test_a_frozen_clock_does_not_move_on_its_own():
    clock = FrozenClock()

    assert clock.now() == clock.now()


def test_a_frozen_clock_moves_exactly_as_far_as_it_is_told():
    clock = FrozenClock()
    before = clock.now()
    clock.advance(seconds=90)

    assert clock.now() - before == datetime.timedelta(seconds=90)


def test_a_frozen_clock_refuses_to_move_backwards():
    """A test that rewinds time is asserting something the system will never see."""
    clock = FrozenClock()

    with pytest.raises(ValueError):
        clock.advance(seconds=-1)


def test_a_frozen_clock_starts_at_a_stated_instant():
    at = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

    assert FrozenClock(at=at).now() == at


def test_both_clocks_satisfy_the_protocol():
    for clock in (SystemClock(), FrozenClock()):
        assert isinstance(clock, Clock)


def _wall_clock_reads(path: pathlib.Path) -> list[str]:
    """AST, not grep. Twice in this repo a source-scanning test has matched its
    own prose; parsing calls cannot."""
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in WALL_CLOCK:
                base = node.func.value
                name = getattr(base, "id", getattr(base, "attr", ""))
                if name in {"datetime", "time"}:
                    found.append(f"{name}.{node.func.attr}()")
    return found


def test_no_module_reads_the_wall_clock_without_an_exemption():
    """Covers apps/ and libs/ by default, so new code is caught automatically.

    A hand-maintained allowlist of files to CHECK would silently stop covering
    the repo the moment it grew -- which is exactly how the doc checker in this
    repo went blind.
    """
    offenders = {}
    for path in sorted([*(REPO / "apps").rglob("*.py"), *(REPO / "libs").rglob("*.py")]):
        rel = str(path.relative_to(REPO))
        if rel in EXEMPT:
            continue
        reads = _wall_clock_reads(path)
        if reads:
            offenders[rel] = reads

    assert not offenders, (
        f"these read the wall clock directly instead of taking a Clock: {offenders}"
    )


def test_every_exemption_is_still_earning_its_place():
    """Stale exemptions accumulate and quietly widen the hole."""
    unnecessary = [
        rel for rel in EXEMPT if not _wall_clock_reads(REPO / rel)
    ]

    assert not unnecessary, f"exemptions no longer needed, remove them: {unnecessary}"
