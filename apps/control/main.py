"""Business control service: reservations against the compensation budget.

The coordination authority the agents lack in P2. It can see the aggregate that
spans Billing and Ledger, so it can refuse an action that would breach the
ceiling even when that action is individually valid.

Reservation is atomic under a transaction-scoped advisory lock keyed on the
case. Without the lock this service would have the very read-check-write race it
exists to prevent -- which would be an ironic and entirely silent defect.

Note what this does NOT do: it does not know what the ceiling should be, which
operations count toward it, or where their state lives. Someone has to specify
that. Enforcement is mechanism; deciding what to enforce is not.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from apps.control.db import connect
from libs.barrier.middleware import ActorContextMiddleware, current_actor
from libs.request_log import RequestLogMiddleware

SERVICE = "control"

app = FastAPI(title="control")
app.add_middleware(ActorContextMiddleware, strict=True)
app.add_middleware(RequestLogMiddleware, connect=connect)


class ReserveRequest(BaseModel):
    case_id: str
    amount: Decimal
    idempotency_key: str
    authorized_compensation: Decimal


@app.post("/reservations", status_code=201)
def reserve(req: ReserveRequest) -> dict:
    actor = current_actor()
    with connect() as conn, conn.cursor() as cur:
        # Serialise all reservation decisions for this case. The check and the
        # insert must be one atomic step, or this service reproduces the race.
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (req.case_id,))

        cur.execute(
            "SELECT id, amount, state FROM reservations WHERE idempotency_key = %s",
            (req.idempotency_key,),
        )
        existing = cur.fetchone()
        if existing is not None:
            conn.commit()
            return {
                "id": existing[0],
                "granted": True,
                "amount": str(existing[1]),
                "replayed": True,
            }

        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM reservations "
            "WHERE case_id = %s AND state IN ('HELD', 'COMMITTED')",
            (req.case_id,),
        )
        held = Decimal(cur.fetchone()[0])

        if held + req.amount > req.authorized_compensation:
            conn.commit()
            raise HTTPException(
                status_code=409,
                detail=(
                    f"reservation refused: {held} already held plus {req.amount} "
                    f"would exceed {req.authorized_compensation}"
                ),
            )

        cur.execute(
            "INSERT INTO reservations "
            "(case_id, actor_id, idempotency_key, amount, state) "
            "VALUES (%s, %s, %s, %s, 'HELD') RETURNING id",
            (req.case_id, actor, req.idempotency_key, req.amount),
        )
        row_id = cur.fetchone()[0]
        conn.commit()

    return {"id": row_id, "granted": True, "amount": str(req.amount),
            "replayed": False}


@app.get("/reservations")
def list_reservations(case_id: str = Query(...)) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM reservations "
            "WHERE case_id = %s AND state IN ('HELD', 'COMMITTED')",
            (case_id,),
        )
        total = cur.fetchone()[0]
    return {"total_held": str(total)}


@app.get("/health")
def health() -> dict:
    import os

    return {"service": SERVICE, "pid": os.getpid()}
