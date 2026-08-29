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

from apps.coordinator.barrier import (
    Barrier,
    BarrierAborted,
    BarrierTimeout,
    Reaper,
)
from apps.coordinator.schedule import Schedule, UndeclaredOccurrence

app = FastAPI(title="agent-control-lab coordinator")

_lock = threading.Lock()
_schedule: Schedule | None = None
_barrier: Barrier | None = None
_timeout: float = 30.0
_lease_ttl: float = 30.0
_reaper: Reaper | None = None
_faults: set = set()


class DeclareRequest(BaseModel):
    schedule_id: str
    steps: list[tuple[str, str]]
    timeout_seconds: float = 30.0
    lease_ttl_seconds: float = 30.0
    # Checkpoints that release the schedule but return a fault to the
    # caller. Models a durable effect whose acknowledgement is lost.
    faults: list[tuple[str, str, int]] = []


class AwaitRequest(BaseModel):
    checkpoint: str


class HeartbeatRequest(BaseModel):
    checkpoint: str
    occurrence: int


def reset_state() -> None:
    global _schedule, _barrier, _timeout, _lease_ttl, _reaper, _faults
    reaper, _reaper = _reaper, None
    if reaper is not None:
        reaper.stop()
    with _lock:
        _schedule = None
        _barrier = None
        _timeout = 30.0
        _lease_ttl = 30.0
        _faults.clear()


def _abort(reason: str) -> None:
    if _barrier is not None:
        _barrier.abort(reason)


@app.post("/declare")
def declare(req: DeclareRequest) -> dict:
    global _schedule, _barrier, _timeout, _lease_ttl, _reaper, _faults
    reset_state()
    with _lock:
        _schedule = Schedule(req.schedule_id, [tuple(s) for s in req.steps])
        _barrier = Barrier(_schedule)
        _timeout = req.timeout_seconds
        _lease_ttl = req.lease_ttl_seconds
        _faults = {tuple(f) for f in req.faults}
        barrier = _barrier
    # Nothing may depend on someone remembering to call reap().
    _reaper = Reaper(barrier, interval=min(1.0, req.lease_ttl_seconds / 3))
    _reaper.start()
    return {
        "schedule_id": req.schedule_id,
        "steps": len(req.steps),
        "timeout_seconds": req.timeout_seconds,
        "lease_ttl_seconds": req.lease_ttl_seconds,
    }


@app.post("/heartbeat")
def heartbeat(
    req: HeartbeatRequest,
    x_actor_id: str | None = Header(default=None),
    x_schedule_id: str | None = Header(default=None),
) -> dict:
    """Refresh a parked waiter's lease.

    Deliberately does NOT abort on a missing header or unknown waiter: a
    heartbeat is an observation, not a schedule step, so a stray one must not be
    able to kill a run. It simply reports that nothing was refreshed.
    """
    if _barrier is None or not x_actor_id:
        return {"refreshed": False}
    refreshed = _barrier.heartbeat(x_actor_id, req.checkpoint, req.occurrence)
    return {"refreshed": refreshed}


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
        occurrence = _barrier.wait(
            x_actor_id,
            req.checkpoint,
            timeout=_timeout,
            lease_ttl=_lease_ttl,
        )
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

    # The schedule has already advanced -- the effect is durable. Only the
    # acknowledgement is withheld, which is exactly the ambiguity being modelled.
    if (x_actor_id, req.checkpoint, occurrence) in _faults:
        raise HTTPException(
            status_code=500,
            detail=(
                f"injected fault: acknowledgement dropped at {req.checkpoint} "
                f"occurrence {occurrence}"
            ),
        )

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
