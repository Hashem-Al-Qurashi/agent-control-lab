"""Task 14: the oracle -- own SQL, read-only, gated on quiescence.

Three structural properties, each guarding a way the verdict stops being
trustworthy:

  own SQL      -- if the oracle imported the services' models or filters, a bug
                  in those would appear in both the system and its judge, and
                  cancel out invisibly
  read-only    -- an oracle that can write can perturb what it measures
  quiescence   -- two independent Postgres admit no cross-database snapshot, so
                  reading mid-flight yields a torn state and an unreproducible
                  verdict

The verdict is COMMITTED-and-not-VOIDED. PENDING-inclusive totals are emitted
alongside but are never the verdict: counting PENDING against the ceiling would
design the fix into the failure, and the rebuttal writes itself -- "then make
PENDING a reservation".
"""

import ast
import pathlib
from decimal import Decimal

import pytest

from apps.billing.db import connect as billing_connect
from apps.billing.db import run_migrations as billing_migrations
from apps.billing.db import truncate_all as billing_truncate
from apps.ledger.db import connect as ledger_connect
from apps.ledger.db import run_migrations as ledger_migrations
from apps.ledger.db import truncate_all as ledger_truncate
from oracle.invariants import Verdict, evaluate
from oracle.quiescence import NotQuiescent, ensure_quiescent, grant_readonly

REPO = pathlib.Path(__file__).resolve().parents[2]
CEILING = Decimal("1000.00")


@pytest.fixture()
def clean_dbs():
    billing_migrations()
    ledger_migrations()
    grant_readonly()
    billing_truncate()
    ledger_truncate()
    yield
    billing_truncate()
    ledger_truncate()


def _insert(conn_fn, table, case_id, actor, amount, state, key):
    with conn_fn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {table} (case_id, actor_id, idempotency_key, amount, state) "
            "VALUES (%s, %s, %s, %s, %s)",
            (case_id, actor, key, amount, state),
        )
        conn.commit()


def test_clean_when_total_is_under_the_ceiling(clean_dbs):
    _insert(billing_connect, "refunds", "c1", "A", "600.00", "COMMITTED", "k1")
    _insert(ledger_connect, "credits", "c1", "B", "300.00", "COMMITTED", "k2")

    result = evaluate("c1", CEILING)

    assert result.verdict is Verdict.CLEAN
    assert result.committed_total == Decimal("900.00")


def test_violation_when_the_sum_exceeds_the_ceiling(clean_dbs):
    _insert(billing_connect, "refunds", "c1", "A", "600.00", "COMMITTED", "k1")
    _insert(ledger_connect, "credits", "c1", "B", "500.00", "COMMITTED", "k2")

    result = evaluate("c1", CEILING)

    assert result.verdict is Verdict.VIOLATION
    assert result.committed_total == Decimal("1100.00")
    assert result.realized_overage == Decimal("100.00")


def test_exactly_at_the_ceiling_is_clean(clean_dbs):
    _insert(billing_connect, "refunds", "c1", "A", "600.00", "COMMITTED", "k1")
    _insert(ledger_connect, "credits", "c1", "B", "400.00", "COMMITTED", "k2")

    assert evaluate("c1", CEILING).verdict is Verdict.CLEAN


def test_voided_rows_are_excluded_from_the_verdict(clean_dbs):
    _insert(billing_connect, "refunds", "c1", "A", "600.00", "COMMITTED", "k1")
    _insert(ledger_connect, "credits", "c1", "B", "500.00", "VOIDED", "k2")

    result = evaluate("c1", CEILING)

    assert result.verdict is Verdict.CLEAN
    assert result.committed_total == Decimal("600.00")


def test_settled_counts_toward_the_verdict(clean_dbs):
    """SETTLED differs from COMMITTED in irreversibility, not in whether the
    money is committed."""
    _insert(billing_connect, "refunds", "c1", "A", "600.00", "SETTLED", "k1")
    _insert(ledger_connect, "credits", "c1", "B", "500.00", "COMMITTED", "k2")

    assert evaluate("c1", CEILING).verdict is Verdict.VIOLATION


def test_pending_is_reported_but_is_not_the_verdict(clean_dbs):
    """Counting PENDING against the ceiling would design the fix into the failure."""
    _insert(billing_connect, "refunds", "c1", "A", "600.00", "COMMITTED", "k1")
    _insert(ledger_connect, "credits", "c1", "B", "500.00", "PENDING", "k2")

    result = evaluate("c1", CEILING)

    assert result.verdict is Verdict.CLEAN
    assert result.committed_total == Decimal("600.00")
    assert result.obligated_total == Decimal("1100.00")
    assert result.obligated_total != result.committed_total


def test_oracle_imports_no_service_code():
    """A shared bug between system and judge would cancel out invisibly."""
    forbidden = ("apps.billing.main", "apps.ledger.main", "libs.service_common")
    for module in ("invariants.py", "sql.py", "quiescence.py"):
        tree = ast.parse((REPO / "oracle" / module).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        leaked = imported & set(forbidden)
        assert not leaked, f"oracle/{module} imports service code: {leaked}"


def test_oracle_credentials_cannot_write(clean_dbs):
    """An oracle that can write can perturb what it measures."""
    from oracle.sql import readonly_connection

    with readonly_connection("billing") as conn, conn.cursor() as cur:
        with pytest.raises(Exception) as exc:
            cur.execute(
                "INSERT INTO refunds (case_id, actor_id, idempotency_key, "
                "amount, state) VALUES ('x','A','zz','1.00','COMMITTED')"
            )
    assert "permission denied" in str(exc.value).lower()


def test_evaluation_refuses_to_run_when_not_quiescent(clean_dbs):
    with pytest.raises(NotQuiescent):
        ensure_quiescent(parked_waiters=[("B", "ledger.x", 0)])


def test_quiescent_when_no_waiters_are_parked(clean_dbs):
    ensure_quiescent(parked_waiters=[])
