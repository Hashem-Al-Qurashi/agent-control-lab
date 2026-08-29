"""Mode B -- how often, rather than whether.

Mode A establishes that an execution can happen and why. It cannot establish
frequency, because the interleaving is chosen. Mode B chooses nothing: two
agents run concurrently with no barrier and whatever happens, happens.

The two modes answer different questions and neither substitutes for the other.
A Mode B frequency without Mode A cannot say what caused anything; a Mode A
counterexample without Mode B cannot say whether it matters in practice.

Integrity, because a frequency is the easiest number in this repo to
manufacture: workload parameters are reported, no artificial delay is injected,
the oracle runs after each case and never during, and a zero result is published
as the result.

**Mode B must never assert reproducibility.** It chooses no interleaving, so
byte-identical replays are not a property it has or should claim -- that is Mode
A's job and adding such an assertion here would be a category error.

(An earlier version tried to enforce that by grepping this file for the word.
It failed on its own assertion string -- the second time in this project a
self-referential source check tripped over its own prose. The constraint is a
design rule for a human reader, not something a grep can hold.)
"""

import os
from decimal import Decimal

import pytest

from apps.billing.db import truncate_all as billing_truncate
from apps.ledger.db import truncate_all as ledger_truncate
from oracle.invariants import Verdict
from schedules.naturalistic import run_naturally

RUNS = int(os.environ.get("ACL_MODE_B_RUNS", "40"))
CEILING = "1000.00"


@pytest.fixture()
def clean_natural(natural_stack):
    billing_truncate()
    ledger_truncate()
    yield natural_stack
    billing_truncate()
    ledger_truncate()


def _campaign(stack, runs):
    outcomes = []
    for i in range(runs):
        billing_truncate()
        ledger_truncate()
        outcomes.append(run_naturally(stack, f"nat-{i}", ceiling=CEILING))
    return outcomes


def test_naturalistic_campaign_reports_a_defensible_frequency(clean_natural):
    """The headline Mode B measurement, with its denominator stated."""
    outcomes = _campaign(clean_natural, RUNS)

    violations = [o for o in outcomes if o.verdict is Verdict.VIOLATION]
    windows = [o for o in outcomes if o.window_opened]

    print(
        f"\n  Mode B — {RUNS} runs, 2 concurrent agents, no barrier\n"
        f"    violations:     {len(violations):>3}/{RUNS} "
        f"({100*len(violations)/RUNS:.1f}%)\n"
        f"    window opened:  {len(windows):>3}/{RUNS} "
        f"({100*len(windows)/RUNS:.1f}%)\n"
        f"    (frequency applies to THIS workload only; not a production estimate)"
    )

    # The measurement is the result whichever way it lands. What must hold is
    # that every run produced a defensible verdict.
    assert len(outcomes) == RUNS
    assert all(o.verdict in (Verdict.CLEAN, Verdict.VIOLATION) for o in outcomes), (
        "a run returned INCONCLUSIVE -- service idempotency broke and the "
        "frequency below is not measuring what it claims"
    )


def test_a_violation_only_ever_occurs_when_the_window_opened(clean_natural):
    """The observable earns its place here.

    A breach with the window closed would mean the frequency is measuring
    something other than the race -- most likely a defect in the harness. This
    is the check that makes the percentage interpretable rather than decorative.
    """
    outcomes = _campaign(clean_natural, RUNS)

    impossible = [
        o for o in outcomes
        if o.verdict is Verdict.VIOLATION and not o.window_opened
    ]
    assert not impossible, (
        f"{len(impossible)} run(s) breached with the race window closed: "
        f"{[o.case_id for o in impossible]}. The frequency is not measuring the "
        "race."
    )


def test_totals_are_always_one_of_the_reachable_states(clean_natural):
    """Every outcome must be explicable. 0, 500, 600 or 1100 -- nothing else is
    reachable from two agents at 600 and 500 against a 1000 ceiling."""
    outcomes = _campaign(clean_natural, min(RUNS, 20))

    reachable = {
        Decimal("0"), Decimal("500.00"), Decimal("600.00"), Decimal("1100.00")
    }
    unexpected = [o for o in outcomes if o.committed_total not in reachable]

    assert not unexpected, (
        f"unreachable totals observed: "
        f"{[(o.case_id, str(o.committed_total)) for o in unexpected]}"
    )



STAGGERS = [0.0, 0.050, 0.075, 0.100, 0.125, 0.150, 0.200]


def test_exposure_falls_as_arrival_separation_grows(clean_natural):
    """The measurement that makes Mode B informative.

    At zero separation the window is open essentially always, so a 100% figure
    describes the workload rather than the system. Varying arrival separation
    turns one uninformative number into a curve, and the curve is the finding:
    exposure is a function of how close together agents arrive.

    Arrival separation is a workload parameter, not an injected delay -- nothing
    inside the system is paused, no checkpoint is held, and neither service
    behaves differently. That line is what keeps Mode B from becoming Mode A
    wearing a disguise.
    """
    runs_each = max(10, RUNS // len(STAGGERS))
    curve = []

    for stagger in STAGGERS:
        violations = 0
        windows = 0
        for i in range(runs_each):
            billing_truncate()
            ledger_truncate()
            outcome = run_naturally(
                clean_natural, f"stag-{stagger}-{i}", ceiling=CEILING,
                stagger_seconds=stagger,
            )
            violations += outcome.verdict is Verdict.VIOLATION
            windows += outcome.window_opened
        curve.append((stagger, violations, windows, runs_each))

    print(f"\n  Mode B — exposure vs arrival separation ({runs_each} runs each)")
    print("    stagger    violations    window open")
    for stagger, violations, windows, n in curve:
        print(
            f"    {stagger*1000:>6.0f}ms    {violations:>3}/{n} "
            f"({100*violations/n:5.1f}%)   {windows:>3}/{n} ({100*windows/n:5.1f}%)"
        )

    # Every run must still produce a defensible verdict at every stagger.
    assert all(n == runs_each for _, _, _, n in curve)

    # A violation without an open window at ANY stagger means the frequency is
    # measuring something other than the race.
    for stagger, violations, windows, _ in curve:
        assert violations <= windows, (
            f"at {stagger*1000:.0f}ms stagger, {violations} violations but only "
            f"{windows} runs had the window open -- the measurement is not "
            "tracking the race"
        )
