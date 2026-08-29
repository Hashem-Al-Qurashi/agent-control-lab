"""Barrier coordinator HTTP surface.

Fails closed. Every error path aborts the run instead of releasing a waiter --
missing header, unknown actor, wrong schedule, or an undeclared occurrence. A
default-releasing barrier manufactures results, so there is deliberately no code
path that returns a release once the run is aborted.

Actor identity arrives as a wire value (X-Actor-Id / X-Schedule-Id). A checkpoint
cannot derive the actor from the runtime: PID, thread id, task id and contextvars
all identify the server's unit of work, not the caller.
"""

from __future__ import annotations

import threading

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from apps.coordinator.barrier import Barrier, BarrierAborted, BarrierTimeout
from apps.coordinator.schedule import Schedule, UndeclaredOccurrence

app = FastAPI(title="agent-control-lab coordinator")

_lock = threading.Lock()
_schedule: Schedule | None = None
_barrier: Barrier | None = None
_timeout: float = 30.0


class DeclareRequest(BaseModel):
    schedule_id: str
    steps: list[tuple[str, str]]
    timeout_seconds: float = 30.0


class AwaitRequest(BaseModel):
    checkpoint: str


def reset_state() -> None:
    global _schedule, _barrier, _timeout
    with _lock:
        _schedule = None
        _barrier = None
        _timeout = 30.0


def _abort(reason: str) -> None:
    if _barrier is not None:
        _barrier.abort(reason)


@app.post("/declare")
def declare(req: DeclareRequest) -> dict:
    global _schedule, _barrier, _timeout
    with _lock:
        _schedule = Schedule(req.schedule_id, [tuple(s) for s in req.steps])
        _barrier = Barrier(_schedule)
        _timeout = req.timeout_seconds
    return {"schedule_id": req.schedule_id, "steps": len(req.steps)}


@app.post("/await")
def await_checkpoint(
    req: AwaitRequest,
    x_actor_id: str | None = Header(default=None),
    x_schedule_id: str | None = Header(default=None),
) -> dict:
    if _barrier is None or _schedule is None:
        raise HTTPException(status_code=409, detail="no schedule declared")

    if _barrier.aborted is not None:
        raise HTTPException(
            status_code=409, detail=f"run aborted: {_barrier.aborted}"
        )

    # Unlabelled requests are rejected in test mode -- an unlabelled arrival
    # cannot be routed to an actor, and guessing would fabricate the schedule.
    if not x_actor_id:
        _abort("missing X-Actor-Id")
        raise HTTPException(status_code=400, detail="missing X-Actor-Id header")
    if not x_schedule_id:
        _abort("missing X-Schedule-Id")
        raise HTTPException(status_code=400, detail="missing X-Schedule-Id header")

    if x_schedule_id != _schedule.schedule_id:
        _abort(f"schedule mismatch: got {x_schedule_id}")
        raise HTTPException(
            status_code=409,
            detail=f"schedule mismatch: expected {_schedule.schedule_id}, "
            f"got {x_schedule_id}",
        )

    if x_actor_id not in _schedule.known_actors:
        _abort(f"unknown actor: {x_actor_id}")
        raise HTTPException(status_code=400, detail=f"unknown actor {x_actor_id}")

    try:
        occurrence = _barrier.wait(x_actor_id, req.checkpoint, timeout=_timeout)
    except UndeclaredOccurrence as exc:
        _abort(str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BarrierAborted as exc:
        raise HTTPException(
            status_code=409, detail=f"run aborted: {exc}"
        ) from exc
    except BarrierTimeout as exc:
        _abort(str(exc))
        raise HTTPException(status_code=504, detail=str(exc)) from exc

    return {"occurrence": occurrence, "checkpoint": req.checkpoint}


@app.get("/waiters")
def waiters() -> dict:
    if _barrier is None or _schedule is None:
        return {
            "schedule_id": None,
            "aborted": False,
            "abort_reason": None,
            "waiters": [],
            "release_order": [],
            "expects": None,
        }
    return {
        "schedule_id": _schedule.schedule_id,
        "aborted": _barrier.aborted is not None,
        "abort_reason": _barrier.aborted,
        "waiters": [list(k) for k in _barrier.waiters()],
        "release_order": [list(k) for k in _barrier.release_order()],
        "expects": list(_schedule.current_step) if _schedule.current_step else None,
    }


@app.post("/reset")
def reset() -> dict:
    if _barrier is not None:
        _barrier.abort("reset")
    reset_state()
    return {"reset": True}
