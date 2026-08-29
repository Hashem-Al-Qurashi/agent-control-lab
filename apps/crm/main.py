"""CRM service: exposes the compensation projection.

What an agent is typically given. It cannot query Billing's or Ledger's
authoritative stores -- it reads the CRM view, because that is the integration
point that exists. The view lags, and the agent's picture is stale through no
fault of its own diligence.

Reads report their own lag. A projection that hides how far behind it is would
make a stale decision indistinguishable from a correct one, which is precisely
the confusion Stage 1 exists to expose rather than reproduce.
"""

from __future__ import annotations

import os
from decimal import Decimal

from fastapi import FastAPI, Query
from pydantic import BaseModel

from apps.crm.db import connect
from apps.crm.projector import apply_pending
from libs.tracing import configure_export
from libs.barrier.middleware import ActorContextMiddleware, current_actor
from libs.request_log import RequestLogMiddleware
from libs.service_common import checkpoint as _checkpoint

SERVICE = "crm"

# Span export is off unless OTEL_EXPORTER_OTLP_ENDPOINT is set. Without this
# call every span in a running service goes to the no-op provider and nothing
# collects it -- tracing that is real in tests and absent in deployment.
configure_export("crm")

app = FastAPI(title="crm")
app.add_middleware(ActorContextMiddleware, strict=True)
app.add_middleware(RequestLogMiddleware, connect=connect)


class HttpEventSource:
    """A service's outbox, read over HTTP.

    Never reaches into another service's database. There is no shared
    transaction boundary between services and that constraint is the premise --
    a projector with direct database access would quietly dissolve it.
    """

    def __init__(
        self, base_url: str, actor: str, schedule: str, case_id: str | None = None
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-Actor-Id": actor, "X-Schedule-Id": schedule}
        self._case_id = case_id

    def unapplied(self) -> list[dict]:
        import httpx

        response = httpx.get(
            f"{self._base}/events",
            params=(
                {"unapplied_only": True, "case_id": self._case_id}
                if self._case_id
                else {"unapplied_only": True}
            ),
            headers=self._headers,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["events"]

    def mark_applied(self, event_id: int) -> None:
        import httpx

        httpx.post(
            f"{self._base}/events/{event_id}/applied",
            headers=self._headers,
            timeout=30.0,
        ).raise_for_status()


@app.get("/compensation")
def get_compensation(case_id: str = Query(...)) -> dict:
    """The projection's view, with its own lag reported alongside."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT total, events_applied FROM compensation_projection "
            "WHERE case_id = %s",
            (case_id,),
        )
        row = cur.fetchone()
    total = Decimal(row[0]) if row else Decimal("0")
    return {
        "case_id": case_id,
        "total_committed": str(total),
        "events_applied": row[1] if row else 0,
        "source": "projection",
    }


class ProjectRequest(BaseModel):
    billing_url: str
    ledger_url: str


@app.post("/project")
def project(req: ProjectRequest) -> dict:
    """Fold pending events into the projection.

    Driven explicitly rather than by a background poller, so a schedule can say
    exactly when the projection is allowed to catch up. A timer would make
    catch-up a race the schedule does not control.
    """
    actor = current_actor() or "projector"
    schedule = os.environ.get("ACL_SCHEDULE_ID", "unscheduled")
    sources = {
        "billing": HttpEventSource(req.billing_url, actor, schedule),
        "ledger": HttpEventSource(req.ledger_url, actor, schedule),
    }
    applied = apply_pending(sources, checkpoint=_checkpoint)
    return {"applied": applied}


@app.get("/health")
def health() -> dict:
    return {"service": SERVICE, "pid": os.getpid()}
