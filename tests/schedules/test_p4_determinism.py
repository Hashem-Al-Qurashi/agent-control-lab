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
        "decision_log": _decision_log(case_id),
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

    for replay in range(REPLAYS):
        billing_truncate()
        ledger_truncate()
        control_truncate()
        outcome = run_schedule(schedule_id, clean_state)
        fingerprints.append(_fingerprint(outcome, case_id))

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
