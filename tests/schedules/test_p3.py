"""P3 -- lost acknowledgement then an explicit keyed retry. MUST PASS.

The primary anti-strawman control. It proves the baseline is not rigged to fail
everywhere: local mechanisms work exactly where they are supposed to.

It also demonstrates -- rather than asserts -- that idempotency is orthogonal to
the aggregate invariant. Idempotency protects one logical operation from being
applied twice. The aggregate is breached by two DIFFERENT valid operations. So
"just add idempotency keys" is not a fix for P2, and this is the evidence.
"""

from decimal import Decimal

import psycopg2

from oracle.invariants import Verdict
from oracle.quiescence import OWNER_DSNS
from schedules.runner import assert_actors_succeeded, run_schedule


def _refund_rows(case_id):
    conn = psycopg2.connect(OWNER_DSNS["billing"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT idempotency_key, amount, state FROM refunds "
                "WHERE case_id = %s ORDER BY id",
                (case_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def test_p3_is_clean(clean_state):
    outcome = run_schedule("P3", clean_state)
    assert_actors_succeeded(outcome)

    assert outcome.result.verdict is Verdict.CLEAN
    assert outcome.result.committed_total == Decimal("600.00")


def test_p3_creates_exactly_one_refund_despite_the_retry(clean_state):
    """The load-bearing assertion: durable work, lost ACK, retry, one effect."""
    run_schedule("P3", clean_state)

    rows = _refund_rows("case-p3")
    assert len(rows) == 1, (
        f"{len(rows)} refund rows after a retry with the same idempotency key -- "
        "service idempotency is broken and the rig cannot be trusted"
    )
    assert rows[0][1] == Decimal("600.00")


def test_p3_is_not_reported_as_inconclusive(clean_state):
    """One key, one effect. If the oracle sees two effects for one key it would
    correctly refuse the run -- so a CLEAN verdict here also confirms
    idempotency held."""
    outcome = run_schedule("P3", clean_state)

    assert outcome.result.verdict is not Verdict.INCONCLUSIVE
    assert outcome.result.reason is None


def test_p3_reached_the_same_checkpoint_at_two_occurrences(clean_state):
    """The original attempt and the retry both traverse the create path.

    This is why the barrier key carries an occurrence index: a three-part key
    would consume the first hit's release token or deadlock here.
    """
    outcome = run_schedule("P3", clean_state)

    reads = [
        r for r in outcome.release_order
        if r[1] == "billing.after_read_before_decide"
    ]
    assert [r[2] for r in reads] == [0, 1]


def test_p3_commits_once_even_though_the_create_path_ran_twice(clean_state):
    """On the retry there is no commit -- the service recognises the key and
    returns the existing row before reaching the post-commit checkpoint. The
    asymmetry between two create attempts and one commit IS the mechanism."""
    outcome = run_schedule("P3", clean_state)

    acks = [
        r for r in outcome.release_order
        if r[1] == "billing.after_commit_before_ack"
    ]
    assert [r[2] for r in acks] == [0]


def test_p3_leaves_no_waiter_parked(clean_state):
    outcome = run_schedule("P3", clean_state)
    assert outcome.parked_waiters == []
