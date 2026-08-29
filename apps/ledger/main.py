"""Ledger service: credits.

Checkpoints are placed at two points that matter to the schedules:

  ledger.after_read_before_decide   -- opens the stale-read window (P2)
  ledger.after_commit_before_ack    -- INSIDE the handler, AFTER the transaction
                                        commits (P3's lost-ACK case)

The second is why header propagation is mandatory rather than optional: at that
point the work is durable but the caller has not been told, and the barrier must
know which actor is sitting there.

Barrier participation is explicit configuration (BARRIER_ENABLED). It is never a
silent fallback -- a checkpoint that no-ops when it cannot reach the coordinator
would fail open, and the whole design is fail-closed.
"""

from __future__ import annotations

import os

from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, field_validator

from apps.ledger.db import connect
from libs.tracing import configure_export
from libs.barrier.middleware import ActorContextMiddleware, current_actor
from libs.request_log import RequestLogMiddleware
from libs.enforcement import authorize
from libs.outbox import publish
from libs.service_common import (
    append_decision,
    checkpoint as _checkpoint,
)

SERVICE = "ledger"

# Span export is off unless OTEL_EXPORTER_OTLP_ENDPOINT is set. Without this
# call every span in a running service goes to the no-op provider and nothing
# collects it -- tracing that is real in tests and absent in deployment.
configure_export("ledger")

app = FastAPI(title="ledger")
app.add_middleware(ActorContextMiddleware, strict=True)
app.add_middleware(RequestLogMiddleware, connect=connect)


class CreditRequest(BaseModel):
    case_id: str
    amount: Decimal
    idempotency_key: str

    @field_validator("amount")
    @classmethod
    def _positive(cls, value: Decimal) -> Decimal:
        """Reject at the boundary, not at the database.

        The CHECK constraint catches this too, but as a 500 -- and an abuse
        attempt that produces a server error is indistinguishable from a real
        outage in every dashboard. A negative amount is also not merely
        malformed: it would INCREASE the budget available to the next actor.
        """
        if value <= 0:
            raise ValueError("amount must be positive")
        return value


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "case_id": row[1],
        "actor_id": row[2],
        "idempotency_key": row[3],
        "amount": str(row[4]),
        "state": row[5],
    }


@app.post("/credits", status_code=201)
def create_credit(req: CreditRequest, request: Request, response_model=None):
    # Authorized BEFORE any effect is written, so a denied action leaves
    # no row and no event rather than relying on a rollback.
    authorize(request, action="credit", amount=req.amount)
    actor = current_actor()
    _checkpoint("ledger.after_read_before_decide")

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, case_id, actor_id, idempotency_key, amount, state "
            "FROM credits WHERE idempotency_key = %s",
            (req.idempotency_key,),
        )
        existing = cur.fetchone()
        if existing is not None:
            # Replay of the same logical operation. Exactly one economic effect.
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=200, content=_row_to_dict(existing))

        cur.execute(
            "INSERT INTO credits (case_id, actor_id, idempotency_key, amount, state) "
            "VALUES (%s, %s, %s, %s, 'COMMITTED') "
            "RETURNING id, case_id, actor_id, idempotency_key, amount, state",
            (req.case_id, actor, req.idempotency_key, req.amount),
        )
        row = cur.fetchone()
        append_decision(
            cur,
            case_id=req.case_id,
            actor_id=actor,
            service=SERVICE,
            entity_id=row[0],
            from_state=None,
            to_state="COMMITTED",
            amount=req.amount,
        )
        # Same cursor, therefore the same transaction as the effect above.
        # Publishing separately could commit the event without the effect, which
        # would make propagation lag a harness bug rather than a real property.
        publish(
            cur,
            case_id=req.case_id,
            actor_id=actor,
            service=SERVICE,
            event_type="CreditCommitted",
            entity_id=row[0],
            amount=req.amount,
        )
        conn.commit()

    # Durable, but the caller has not been told yet. This is where P3 drops the ACK.
    _checkpoint("ledger.after_commit_before_ack")
    return _row_to_dict(row)


@app.post("/credits/{credit_id}/void")
def void_credit(credit_id: int) -> dict:
    actor = current_actor()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE credits SET state = 'VOIDED' WHERE id = %s "
            "RETURNING id, case_id, actor_id, idempotency_key, amount, state",
            (credit_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="credit not found")
        append_decision(
            cur,
            case_id=row[1],
            actor_id=actor,
            service=SERVICE,
            entity_id=row[0],
            from_state="COMMITTED",
            to_state="VOIDED",
            amount=row[4],
        )
        conn.commit()
    return _row_to_dict(row)


@app.get("/credits")
def list_credits(case_id: str = Query(...)) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, case_id, actor_id, idempotency_key, amount, state "
            "FROM credits WHERE case_id = %s ORDER BY id",
            (case_id,),
        )
        rows = [_row_to_dict(r) for r in cur.fetchall()]
        # COMMITTED and not VOIDED is the verdict definition. SETTLED counts too:
        # it differs from COMMITTED only in irreversibility, not in whether the
        # money is committed.
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM credits "
            "WHERE case_id = %s AND state IN ('COMMITTED', 'SETTLED')",
            (case_id,),
        )
        total = cur.fetchone()[0]
    return {"credits": rows, "total_committed": str(total)}


@app.get("/health")
def health() -> dict:
    """Reports the serving process id.

    Used to prove requests were handled by distinct worker processes. A
    configured worker count is an intention; distinct pids are evidence.
    """
    return {"service": SERVICE, "pid": os.getpid()}


@app.get("/events")
def list_events(unapplied_only: bool = True, case_id: str | None = None) -> dict:
    """Expose this service's outbox.

    The projector reads events over HTTP rather than reaching into this
    service's database. There is no shared transaction boundary between
    services, and that constraint is the premise of the experiment -- a
    projector with direct database access would quietly dissolve it.
    """
    # Scoped to a case. Without this a projector consumes events from every
    # earlier run, hits more checkpoints than its schedule declared, and the
    # barrier aborts it -- while the run still produces numbers that look real.
    where, params = [], []
    if unapplied_only:
        where.append("applied_at IS NULL")
    if case_id is not None:
        where.append("case_id = %s")
        params.append(case_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, case_id, actor_id, service, event_type, entity_id, amount "
            f"FROM outbox {clause} ORDER BY id",
            params,
        )
        events = [
            {
                "id": r[0], "case_id": r[1], "actor_id": r[2], "service": r[3],
                "event_type": r[4], "entity_id": r[5], "amount": str(r[6]),
            }
            for r in cur.fetchall()
        ]
    return {"events": events, "pending": len(events) if unapplied_only else None}


@app.post("/events/{event_id}/applied")
def mark_event_applied(event_id: int) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE outbox SET applied_at = now() WHERE id = %s RETURNING id",
            (event_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="event not found")
        conn.commit()
    return {"id": row[0], "applied": True}


@app.post("/events/redeliver")
def redeliver_events(case_id: str = Query(...)) -> dict:
    """Offer already-applied events again, as an at-least-once bus would.

    Not a production endpoint. It exists so a schedule can exercise redelivery
    deterministically rather than hoping a real bus duplicates at the right
    moment -- the projection's guard against double-counting has to be provable,
    not assumed.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE outbox SET applied_at = NULL WHERE case_id = %s "
            "AND applied_at IS NOT NULL RETURNING id",
            (case_id,),
        )
        ids = [r[0] for r in cur.fetchall()]
        conn.commit()
    return {"redelivered": ids}
