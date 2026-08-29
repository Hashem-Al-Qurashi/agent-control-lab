"""Bind actor identity from the wire to request scope at the ingress boundary.

A checkpoint inside a service cannot derive the actor from the runtime: PID,
thread id, asyncio task id and contextvars all identify the *server's* unit of
work, not the caller. Two actors traverse the same handler on the same server.

So identity arrives as a header and is bound to a request-scoped contextvar.
Binding an explicit wire value to request scope is correct; *inferring* identity
from runtime state is what is forbidden. The failure mode of getting this wrong
is silent -- the barrier releases the wrong actor and the run goes green with a
fabricated schedule.

Implemented as pure ASGI rather than BaseHTTPMiddleware: BaseHTTPMiddleware can
run the downstream app in a separate task, which breaks contextvar propagation
to the endpoint.
"""

from __future__ import annotations

import json
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

ACTOR_HEADER = "x-actor-id"
SCHEDULE_HEADER = "x-schedule-id"

_actor: ContextVar[str | None] = ContextVar("actor_id", default=None)
_schedule: ContextVar[str | None] = ContextVar("schedule_id", default=None)


class MissingActorIdentity(Exception):
    """Identity was read outside a labelled request.

    Raised rather than returning a stale or default value: a silently wrong
    actor id is the exact failure this module exists to prevent.
    """


def current_actor() -> str | None:
    return _actor.get()


def current_schedule() -> str | None:
    return _schedule.get()


def outbound_headers() -> dict[str, str]:
    """Headers every outbound call must carry.

    Enforced here rather than left to convention -- a service that calls another
    service without forwarding identity silently detaches the downstream
    checkpoint from the actor that caused it.
    """
    actor, schedule = _actor.get(), _schedule.get()
    if actor is None or schedule is None:
        raise MissingActorIdentity(
            "no actor identity bound; outbound calls must forward the inbound actor"
        )
    return {"X-Actor-Id": actor, "X-Schedule-Id": schedule}


class ActorContextMiddleware:
    def __init__(self, app: ASGIApp, strict: bool = True) -> None:
        self.app = app
        self.strict = strict

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        actor = headers.get(ACTOR_HEADER)
        schedule = headers.get(SCHEDULE_HEADER)

        if self.strict:
            missing = None
            if not actor:
                missing = "X-Actor-Id"
            elif not schedule:
                missing = "X-Schedule-Id"
            if missing:
                await _reject(send, f"missing {missing} header")
                return

        actor_token = _actor.set(actor)
        schedule_token = _schedule.set(schedule)
        try:
            await self.app(scope, receive, send)
        finally:
            _actor.reset(actor_token)
            _schedule.reset(schedule_token)


async def _reject(send: Send, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
