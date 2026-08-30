"""P4 -- replay determinism.

The anomaly this guards is the one that invalidates the whole method. If the
same declared schedule produces different transition sequences across replays,
then no verdict from this rig is reproducible, and a "violation" cannot be
distinguished from scheduling luck. It is also the finding most tempting to
explain away as flakiness.

The fingerprint is the barrier's release order plus the append-only decision
log, normalised: database ids and timestamps are dropped because they are
expected to differ, while actor, service, state transition and amount are not.

Replay count defaults low so the suite stays usable, and is raised via
ACL_REPLAYS for a confirmatory run. The count is reported in the failure message
so a result is never quoted without knowing how hard it was tested.
"""

import os

import psycopg2
import pytest

from oracle.quiescence import OWNER_DSNS
from schedules.runner import run_schedule

REPLAYS = int(os.environ.get("ACL_REPLAYS", "5"))
SCHEDULES = ["P0", "P1", "P2", "P3"]


def _decision_log(case_id):
    rows = []
    for service in ("billing", "ledger"):
        conn = psycopg2.connect(OWNER_DSNS[service])
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sequence, actor_id, service, from_state, to_state, "
                    "amount FROM decision_log WHERE case_id = %s ORDER BY sequence",
                    (case_id,),
                )
                rows.extend(cur.fetchall())
        finally:
            conn.close()
    # Sorted so the union across two independent databases has a total order
    # that does not depend on which connection returned first.
    return sorted((str(r[0]), r[1], r[2], str(r[3]), str(r[4]), str(r[5]))
                  for r in rows)


def _fingerprint(outcome, case_id):
    return {
        "verdict": outcome.result.verdict.value,
        "committed_total": str(outcome.result.committed_total),
        "release_order": [tuple(r) for r in outcome.release_order],
        # From the outcome, not a fresh read -- see ADR-007.
        "decision_log": list(outcome.transitions),
        "parked": [tuple(w) for w in outcome.parked_waiters],
    }


@pytest.mark.parametrize("schedule_id", SCHEDULES)
def test_schedule_replays_identically(schedule_id, clean_state, request):
    """Every replay must produce a byte-identical normalised transition sequence."""
    from apps.billing.db import truncate_all as billing_truncate
    from apps.control.db import truncate_all as control_truncate
    from apps.ledger.db import truncate_all as ledger_truncate

    case_id = f"case-{schedule_id.lower()}"
    fingerprints = []

    def _reject_corrupt(fp, replay, reference=None):
        """A destroyed sample is not a divergent one.

        Fails loudly rather than skipping: a run that silently drops samples
        would quietly weaken the replay count that the whole determinism claim
        rests on.
        """
        from decimal import Decimal

        from schedules.runner import CorruptSample

        if Decimal(fp["committed_total"]) > 0 and not fp["decision_log"]:
            raise CorruptSample(
                f"replay {replay}: {fp['committed_total']} committed but no "
                "transitions recorded. Something truncated decision_log during "
                "the run -- this sample is destroyed, not divergent. Run the "
                "determinism suite alone (see ADR-007)."
            )
        # A fully truncated sample is internally CONSISTENT -- zero committed,
        # empty log -- so the check above cannot see it. Comparing against the
        # reference replay can: a run that recorded nothing where the reference
        # recorded something did not behave differently, it lost its evidence.
        if reference is not None and reference["decision_log"] and not fp["decision_log"]:
            raise CorruptSample(
                f"replay {replay}: recorded no transitions where replay 0 "
                f"recorded {len(reference['decision_log'])}. The tables were "
                "emptied under this run. Run the determinism suite alone."
            )

    for replay in range(REPLAYS):
        billing_truncate()
        ledger_truncate()
        control_truncate()
        outcome = run_schedule(schedule_id, clean_state)
        fp = _fingerprint(outcome, case_id)
        _reject_corrupt(fp, replay, fingerprints[0] if fingerprints else None)
        fingerprints.append(fp)

    first = fingerprints[0]
    for i, fp in enumerate(fingerprints[1:], start=1):
        assert fp == first, (
            f"{schedule_id} replay {i} of {REPLAYS} diverged from replay 0.\n"
            "Determinism is broken, which invalidates the method itself -- no "
            "verdict from this rig is reproducible until it is fixed. Do not "
            "dismiss this as flakiness.\n"
            f"replay 0: {first}\nreplay {i}: {fp}"
        )


def test_p2_verdict_is_stable_across_replays(clean_state):
    """The violation must be the same violation every time, not merely 'a' one."""
    from apps.billing.db import truncate_all as billing_truncate
    from apps.control.db import truncate_all as control_truncate
    from apps.ledger.db import truncate_all as ledger_truncate

    totals = set()
    for _ in range(REPLAYS):
        billing_truncate()
        ledger_truncate()
        control_truncate()
        outcome = run_schedule("P2", clean_state)
        totals.add((outcome.result.verdict.value,
                    str(outcome.result.committed_total),
                    str(outcome.result.realized_overage)))

    assert totals == {("VIOLATION", "1100.00", "100.00")}, totals


def test_a_fingerprint_survives_the_tables_being_truncated_under_it(clean_state):
    """The fingerprint must describe the run, not the database's current mood.

    ADR-007 spent its life suspecting the scheduler. The captured diff showed
    the barrier's release order was identical across 500 replays under hostile
    load, and the ONLY differing field was decision_log -- empty, because
    another process truncated the table between the run and the fingerprint's
    read of it.

    So the divergence was the measurement reading mutable state that was not
    part of the run it was describing. Fingerprinting the same outcome twice
    must give the same answer even if the tables are emptied in between.
    """
    from apps.billing.db import truncate_all as billing_truncate
    from apps.ledger.db import truncate_all as ledger_truncate
    from schedules.runner import run_schedule

    outcome = run_schedule("P2", clean_state)
    before = _fingerprint(outcome, outcome.result.case_id)

    # Exactly what the integration fixtures and the report generator do between
    # tests, and what made this look like nondeterminism.
    billing_truncate()
    ledger_truncate()

    after = _fingerprint(outcome, outcome.result.case_id)

    assert after == before, (
        "the fingerprint changed because the tables were truncated under it; "
        "it is reading state outside the run it claims to describe"
    )


def test_a_fingerprint_with_committed_money_always_has_a_decision_log(clean_state):
    """The invariant that would have caught this on day one.

    A run that committed money and recorded no transitions is not a divergent
    replay -- it is a sample whose evidence was destroyed. Distinguishing those
    two is the whole of what ADR-007 was missing.
    """
    from decimal import Decimal

    from schedules.runner import run_schedule

    outcome = run_schedule("P2", clean_state)
    print_me = _fingerprint(outcome, outcome.result.case_id)

    if Decimal(print_me["committed_total"]) > 0:
        assert print_me["decision_log"], (
            "money committed but no transitions recorded -- the sample is "
            "corrupt, not divergent"
        )
