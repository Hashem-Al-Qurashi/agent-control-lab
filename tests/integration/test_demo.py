"""The demo must keep demonstrating, or fail loudly.

A demo is the one artifact whose breakage is discovered in front of an audience.
Worse, it breaks quietly: a script that stops reaching the violation still runs,
still prints, and still looks like a demo. So the assertions here are about the
CONTENT of what it showed, not merely that it exited zero.
"""

import subprocess
import sys

import pytest

REPO = __import__("pathlib").Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def demo_output():
    completed = subprocess.run(
        [sys.executable, "demo/run.py"],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )
    return completed


def test_the_demo_exits_cleanly(demo_output):
    """Non-zero on a breach would be wrong: the breach is the expected result."""
    assert demo_output.returncode == 0, demo_output.stderr[-2000:]


def test_the_demo_reaches_a_violation(demo_output):
    """The whole point. A demo that stops breaching is broken and silent."""
    assert "VIOLATION" in demo_output.stdout


def test_the_demo_states_the_overage(demo_output):
    """Not just that it broke -- by how much, so the number is on screen."""
    assert "1100.00" in demo_output.stdout
    assert "1000.00" in demo_output.stdout


def test_the_demo_shows_every_health_signal_green(demo_output):
    """The finding is the AGREEMENT of the green signals with the wrong money.

    If any of the three stopped reporting healthy, the demo would be showing an
    ordinary outage instead, and the argument would silently invert.
    """
    for signal in ("agents", "trace", "reconciliation"):
        assert signal in demo_output.stdout.lower(), (
            f"{signal} signal missing from the demo output"
        )
    assert "OK" in demo_output.stdout


def test_the_demo_never_reports_an_error_signal(demo_output):
    """A red signal anywhere means something actually broke, which is a
    different and much less interesting story than the one being told.

    Checked against the SIGNAL LINES, not against the word "failed" anywhere in
    the output. The first version of this test searched the whole transcript and
    matched the demo's own closing line, "No component failed." That is the
    third time in this repository a source-scanning assertion has matched its
    own prose, so this one reads structure instead of English.
    """
    import re

    plain = re.sub(r"\x1b\[[0-9;]*m", "", demo_output.stdout)
    signal_lines = [
        line for line in plain.splitlines()
        if line.strip().startswith(("agents", "trace", "reconciliation"))
    ]

    assert len(signal_lines) == 3, f"expected three signal lines, got {signal_lines}"
    for line in signal_lines:
        assert "ERROR" not in line and "FINDINGS" not in line, line
    assert "Traceback" not in plain


def test_the_harness_leaves_nothing_running_when_startup_fails():
    """Found by the orphan guard, after three leaked coordinators.

    run_s1 spawned the coordinator BEFORE its try/finally, so any failure
    between the spawn and the block -- a service that never became healthy, for
    instance -- left it running forever. Three of those accumulated during
    development and tripped ADR-007's guard, erroring 65 tests that had nothing
    to do with the demo.
    """
    import subprocess as sp

    import demo.harness as harness

    def _explode(url):
        raise RuntimeError("simulated startup failure")

    before = sp.run(["pgrep", "-f", r"uvicorn apps\."],
                    capture_output=True, text=True).stdout.split()

    original = harness._wait_plain
    harness._wait_plain = _explode
    try:
        with pytest.raises(RuntimeError, match="simulated startup failure"):
            harness.run_s1()
    finally:
        harness._wait_plain = original

    after = sp.run(["pgrep", "-f", r"uvicorn apps\."],
                   capture_output=True, text=True).stdout.split()

    assert set(after) <= set(before), (
        f"startup failure leaked processes: {set(after) - set(before)}"
    )
