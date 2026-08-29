"""Compare what the service APIs reported against what the databases hold.

The agent sees the system through its APIs. The oracle sees the databases. When
those disagree, the gap is the result: the system reported success while the
business state was already wrong -- the failure nobody's monitoring catches
because nothing errored.

Both numbers are kept. Silently preferring one would destroy the only evidence
that the system's own account of itself was unreliable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from fastapi.testclient import TestClient

from oracle import sql


@dataclass(frozen=True)
class ViewComparison:
    case_id: str
    sql_total: Decimal
    api_total: Decimal

    @property
    def delta(self) -> Decimal:
        return abs(self.sql_total - self.api_total)

    @property
    def diverged(self) -> bool:
        # Direction-agnostic: an API claiming more than is true is as much a
        # defect as one claiming less.
        return self.sql_total != self.api_total

    @property
    def summary(self) -> str:
        return (
            f"case {self.case_id}: the API reported {self.api_total} while the "
            f"database held {self.sql_total}"
        )

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "sql_total": str(self.sql_total),
            "api_total": str(self.api_total),
            "delta": str(self.delta),
            "diverged": self.diverged,
            "summary": self.summary,
        }


def _default_api_reader(case_id: str) -> Decimal:
    """Read each service's own reported total over its HTTP surface."""
    from apps.billing.main import app as billing_app
    from apps.ledger.main import app as ledger_app

    headers = {"X-Actor-Id": "ORACLE", "X-Schedule-Id": "observation"}
    total = Decimal("0")
    for app, collection in ((billing_app, "refunds"), (ledger_app, "credits")):
        with TestClient(app) as client:
            response = client.get(
                f"/{collection}", params={"case_id": case_id}, headers=headers
            )
            total += Decimal(response.json()["total_committed"])
    return total


def capture_views(
    case_id: str, api_reader: Callable[[str], Decimal] | None = None
) -> ViewComparison:
    reader = api_reader or _default_api_reader
    return ViewComparison(
        case_id=case_id,
        sql_total=sql.committed_total(case_id),
        api_total=reader(case_id),
    )
