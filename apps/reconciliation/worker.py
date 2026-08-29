"""The reconciler a competent team would actually run.

LAB-SPEC's baseline credibility standard requires competent DETECTION, not only
competent controls. Without a real reconciler, "the violation went undetected"
would be manufactured -- nothing caught it because nothing was looking.

What it checks, deliberately: generic operational anomalies. A projection
lagging. A projection whose total disagrees with the events it applied.
Duplicate idempotency keys. Applied events with no source.

What it does NOT check, equally deliberately: the aggregate ceiling. That is the
solution under test. Handing it to the baseline would assume the answer and make
the silent-failure finding circular -- the system would "detect" the breach only
because we told it the rule we are asking whether anyone knows.

So the honest question this poses is: does ordinary monitoring surface a
business-invariant breach? Expected answer: no. That is a finding, not a defect
in this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

import psycopg2

BILLING_DSN = os.environ.get(
    "BILLING_DSN", "postgresql://billing:billing@127.0.0.1:55433/billing"
)
LEDGER_DSN = os.environ.get(
    "LEDGER_DSN", "postgresql://ledger:ledger@127.0.0.1:55434/ledger"
)
CRM_DSN = os.environ.get("CRM_DSN", "postgresql://crm:crm@127.0.0.1:55436/crm")

SOURCES = {"billing": (BILLING_DSN, "refunds"), "ledger": (LEDGER_DSN, "credits")}


class FindingType(Enum):
    PROJECTION_LAG = "PROJECTION_LAG"
    PROJECTION_DRIFT = "PROJECTION_DRIFT"
    DUPLICATE_IDEMPOTENCY_KEY = "DUPLICATE_IDEMPOTENCY_KEY"
    ORPHANED_APPLIED_EVENT = "ORPHANED_APPLIED_EVENT"


@dataclass(frozen=True)
class Finding:
    type: FindingType
    service: str
    detail: str


@dataclass
class ReconciliationReport:
    case_id: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings


def _query(dsn: str, sql: str, params=()):
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def _check_lag(case_id: str) -> list[Finding]:
    findings = []
    for service, (dsn, _) in SOURCES.items():
        rows = _query(
            dsn,
            "SELECT count(*) FROM outbox WHERE case_id = %s AND applied_at IS NULL",
            (case_id,),
        )
        pending = rows[0][0]
        if pending:
            findings.append(
                Finding(
                    FindingType.PROJECTION_LAG, service,
                    f"{pending} event(s) published but not yet applied",
                )
            )
    return findings


def _check_drift(case_id: str) -> list[Finding]:
    """The projection's own total must equal what it recorded applying."""
    rows = _query(
        CRM_DSN,
        "SELECT total, events_applied FROM compensation_projection WHERE case_id = %s",
        (case_id,),
    )
    if not rows:
        return []
    total, events_applied = Decimal(rows[0][0]), rows[0][1]

    applied = _query(
        CRM_DSN,
        "SELECT COALESCE(SUM(amount), 0), count(*) FROM applied_events "
        "WHERE case_id = %s",
        (case_id,),
    )
    applied_sum, applied_count = Decimal(applied[0][0]), applied[0][1]

    findings = []
    if total != applied_sum or events_applied != applied_count:
        findings.append(
            Finding(
                FindingType.PROJECTION_DRIFT, "crm",
                f"projection reports {total} over {events_applied} event(s) but "
                f"has applied {applied_sum} over {applied_count}",
            )
        )
    return findings


def _check_duplicate_keys(case_id: str) -> list[Finding]:
    findings = []
    for service, (dsn, table) in SOURCES.items():
        rows = _query(
            dsn,
            f"SELECT idempotency_key, count(*) FROM {table} WHERE case_id = %s "
            "GROUP BY idempotency_key HAVING count(*) > 1",
            (case_id,),
        )
        for key, count in rows:
            findings.append(
                Finding(
                    FindingType.DUPLICATE_IDEMPOTENCY_KEY, service,
                    f"key {key!r} appears {count} times",
                )
            )
    return findings


def _check_orphans(case_id: str) -> list[Finding]:
    """An applied event whose source no longer has a matching outbox row."""
    findings = []
    applied = _query(
        CRM_DSN,
        "SELECT source_service, source_id FROM applied_events WHERE case_id = %s",
        (case_id,),
    )
    for service, source_id in applied:
        if service not in SOURCES:
            continue
        dsn, _ = SOURCES[service]
        rows = _query(dsn, "SELECT 1 FROM outbox WHERE id = %s", (source_id,))
        if not rows:
            findings.append(
                Finding(
                    FindingType.ORPHANED_APPLIED_EVENT, service,
                    f"applied event {source_id} has no source row",
                )
            )
    return findings


def reconcile(case_id: str) -> ReconciliationReport:
    report = ReconciliationReport(case_id=case_id)
    report.findings.extend(_check_lag(case_id))
    report.findings.extend(_check_drift(case_id))
    report.findings.extend(_check_duplicate_keys(case_id))
    report.findings.extend(_check_orphans(case_id))
    return report
