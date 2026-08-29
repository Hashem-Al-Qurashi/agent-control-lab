"""Billing service: refunds.

Checkpoints are placed at two points that matter to the schedules:

  billing.after_read_before_decide   -- opens the stale-read window (P2)
  billing.after_commit_before_ack    -- INSIDE the handler, AFTER the transaction
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

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from apps.billing.db import connect
from libs.barrier.middleware import ActorContextMiddleware, current_actor
from libs.service_common import append_decision, checkpoint as _checkpoint

SERVICE = "billing"

app = FastAPI(title="billing")
app.add_middleware(ActorContextMiddleware, strict=True)


class RefundRequest(BaseModel):
    case_id: str
    amount: Decimal
    idempotency_key: str


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "case_id": row[1],
        "actor_id": row[2],
        "idempotency_key": row[3],
        "amount": str(row[4]),
        "state": row[5],
    }


@app.post("/refunds", status_code=201)
def create_refund(req: RefundRequest, response_model=None):
    actor = current_actor()
    _checkpoint("billing.after_read_before_decide")

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, case_id, actor_id, idempotency_key, amount, state "
            "FROM refunds WHERE idempotency_key = %s",
            (req.idempotency_key,),
        )
        existing = cur.fetchone()
        if existing is not None:
            # Replay of the same logical operation. Exactly one economic effect.
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=200, content=_row_to_dict(existing))

        cur.execute(
            "INSERT INTO refunds (case_id, actor_id, idempotency_key, amount, state) "
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
        conn.commit()

    # Durable, but the caller has not been told yet. This is where P3 drops the ACK.
    _checkpoint("billing.after_commit_before_ack")
    return _row_to_dict(row)


@app.post("/refunds/{refund_id}/void")
def void_refund(refund_id: int) -> dict:
    actor = current_actor()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE refunds SET state = 'VOIDED' WHERE id = %s "
            "RETURNING id, case_id, actor_id, idempotency_key, amount, state",
            (refund_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="refund not found")
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


@app.get("/refunds")
def list_refunds(case_id: str = Query(...)) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, case_id, actor_id, idempotency_key, amount, state "
            "FROM refunds WHERE case_id = %s ORDER BY id",
            (case_id,),
        )
        rows = [_row_to_dict(r) for r in cur.fetchall()]
        # COMMITTED and not VOIDED is the verdict definition. SETTLED counts too:
        # it differs from COMMITTED only in irreversibility, not in whether the
        # money is committed.
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM refunds "
            "WHERE case_id = %s AND state IN ('COMMITTED', 'SETTLED')",
            (case_id,),
        )
        total = cur.fetchone()[0]
    return {"refunds": rows, "total_committed": str(total)}


@app.get("/health")
def health() -> dict:
    """Reports the serving process id.

    Used to prove requests were handled by distinct worker processes. A
    configured worker count is an intention; distinct pids are evidence.
    """
    return {"service": SERVICE, "pid": os.getpid()}
