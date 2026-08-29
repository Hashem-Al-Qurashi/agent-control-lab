"""Entitlements service: feature grants.

Owns grants. Does not own the plan -- that lives in Billing. An agent granting a
feature therefore has to consult something outside this service to know whether
the grant is permitted, which is exactly the shape that breaks.

No sums anywhere. If the same failure appears here, the result was never about
arithmetic.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Query
from pydantic import BaseModel

from apps.entitlements.db import connect
from libs.barrier.middleware import ActorContextMiddleware, current_actor
from libs.request_log import RequestLogMiddleware
from libs.service_common import checkpoint as _checkpoint

SERVICE = "entitlements"

app = FastAPI(title="entitlements")
app.add_middleware(ActorContextMiddleware, strict=True)
app.add_middleware(RequestLogMiddleware, connect=connect)


class GrantRequest(BaseModel):
    case_id: str
    feature: str
    idempotency_key: str


def _row(r) -> dict:
    return {"id": r[0], "case_id": r[1], "actor_id": r[2], "feature": r[3],
            "state": r[4]}


@app.post("/features", status_code=201)
def grant_feature(req: GrantRequest):
    actor = current_actor()
    _checkpoint("entitlements.after_read_before_decide")

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, case_id, actor_id, feature, state FROM feature_grants "
            "WHERE idempotency_key = %s",
            (req.idempotency_key,),
        )
        existing = cur.fetchone()
        if existing is not None:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=200, content=_row(existing))

        cur.execute(
            "INSERT INTO feature_grants (case_id, actor_id, idempotency_key, "
            "feature, state) VALUES (%s, %s, %s, %s, 'GRANTED') "
            "RETURNING id, case_id, actor_id, feature, state",
            (req.case_id, actor, req.idempotency_key, req.feature),
        )
        row = cur.fetchone()
        conn.commit()

    _checkpoint("entitlements.after_commit_before_ack")
    return _row(row)


@app.get("/features")
def list_features(case_id: str = Query(...)) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, case_id, actor_id, feature, state FROM feature_grants "
            "WHERE case_id = %s ORDER BY id",
            (case_id,),
        )
        rows = [_row(r) for r in cur.fetchall()]
    return {
        "grants": rows,
        "granted": sorted({r["feature"] for r in rows if r["state"] == "GRANTED"}),
    }


@app.get("/health")
def health() -> dict:
    return {"service": SERVICE, "pid": os.getpid()}
