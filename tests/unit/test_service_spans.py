"""Services must emit spans, not merely be able to.

libs/tracing.py provides span(), and tests/unit/test_tracing.py proves it works.
Nothing in apps/ or agents/ ever called it. So the library was verified, the
system was uninstrumented, and every document claiming "one trace spans the
decision and every call it caused" was describing a capability rather than a
deployment.

That is the defect this repo exists to describe, committed in this repo: a green
test covering a component, and the property it implies about the system absent.
These tests assert the system-level property instead.
"""

from opentelemetry import trace
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from libs.barrier.middleware import ActorContextMiddleware


def _app():
    async def ok(request):
        return JSONResponse({"ok": True})

    async def boom(request):
        raise RuntimeError("downstream exploded")

    app = Starlette(routes=[Route("/ok", ok), Route("/boom", boom)])
    return TestClient(
        ActorContextMiddleware(app, strict=False), raise_server_exceptions=False
    )


def _headers(traceparent=None):
    h = {"X-Actor-Id": "A", "X-Schedule-Id": "S1"}
    if traceparent:
        h["traceparent"] = traceparent
    return h


def test_a_request_produces_a_server_span(spans):
    _app().get("/ok", headers=_headers())

    names = [s.name for s in spans.get_finished_spans()]
    assert names, "the request produced no span at all"


def test_the_span_carries_the_actor_and_schedule(spans):
    """A span that cannot be attributed to an actor cannot answer 'who did this'."""
    _app().get("/ok", headers=_headers())

    recorded = spans.get_finished_spans()[0]
    assert recorded.attributes["acl.actor_id"] == "A"
    assert recorded.attributes["acl.schedule_id"] == "S1"


def test_the_server_span_joins_an_inbound_trace(spans):
    """The property the docs claim: ONE trace across the service boundary.

    Without this the caller and callee each start their own trace, and the
    distributed trace is a collection of unrelated fragments.
    """
    inbound = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    _app().get("/ok", headers=_headers(inbound))

    recorded = spans.get_finished_spans()[0]
    assert format(recorded.context.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert format(recorded.parent.span_id, "016x") == "00f067aa0ba902b7"


def test_a_failing_request_produces_an_error_span(spans):
    """S1's finding is that every span is GREEN while the money is wrong.

    That sentence is only meaningful if a real failure would have been red --
    otherwise every span is green regardless and the observation says nothing.
    """
    _app().get("/boom", headers=_headers())

    recorded = spans.get_finished_spans()[0]
    assert recorded.status.status_code == trace.StatusCode.ERROR


def test_a_successful_request_is_not_marked_as_an_error(spans):
    _app().get("/ok", headers=_headers())

    recorded = spans.get_finished_spans()[0]
    assert recorded.status.status_code != trace.StatusCode.ERROR
