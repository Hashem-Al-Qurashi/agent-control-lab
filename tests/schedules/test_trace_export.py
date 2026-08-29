"""The trace S1 produces, verified against a real collector.

Every other tracing test uses an in-memory exporter, which proves the library
works inside one process. That is what let the system go uninstrumented while
the tests stayed green: no service or agent ever called span(), so in a running
deployment each request began its own trace and the agent emitted nothing.

This test asserts the deployed property instead -- spans leave the processes,
arrive at a collector, and form ONE trace across the service boundary.

Skipped unless Tempo is running and export is configured (`make observability`,
then set OTEL_EXPORTER_OTLP_ENDPOINT), because it needs a real collector.
"""

import os
import time

import httpx
import pytest

TEMPO = "http://127.0.0.1:3200"
pytestmark = pytest.mark.skipif(
    not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
    reason="span export is off; run with OTEL_EXPORTER_OTLP_ENDPOINT set",
)


def _tempo_up() -> bool:
    try:
        return httpx.get(f"{TEMPO}/ready", timeout=2.0).status_code == 200
    except Exception:
        return False


def _search(query: str, window: int = 600):
    now = int(time.time())
    r = httpx.get(
        f"{TEMPO}/api/search",
        params={"q": query, "start": now - window, "end": now + 60, "limit": 20},
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json().get("traces", []) or []


def _spans(trace_id: str):
    payload = httpx.get(f"{TEMPO}/api/traces/{trace_id}", timeout=15.0).json()
    out = []
    for batch in payload.get("batches", payload.get("resourceSpans", [])):
        names = [
            a["value"]["stringValue"]
            for a in batch["resource"]["attributes"]
            if a["key"] == "service.name"
        ]
        service = names[0] if names else "?"
        for scope in batch.get(
            "scopeSpans", batch.get("instrumentationLibrarySpans", [])
        ):
            for span in scope.get("spans", []):
                out.append(
                    {
                        "service": service,
                        "name": span.get("name"),
                        "parent": span.get("parentSpanId") or None,
                        "status": span.get("status", {}).get("code"),
                    }
                )
    return out


_CACHE: dict = {}


@pytest.fixture
def s1_trace(clean_state):
    """Run S1 with export on and return the spans of the trace it produced.

    Function-scoped because clean_state is, but cached: the run takes ~20s and
    all three assertions interrogate the same trace.
    """
    if "spans" in _CACHE:
        return _CACHE["spans"]
    if not _tempo_up():
        pytest.skip("Tempo is not running -- start it with `make observability`")

    from schedules.runner import run_schedule

    run_schedule("s1", clean_state)

    # BatchSpanProcessor flushes on an interval and Tempo needs a moment before
    # a flushed block is queryable. Poll rather than sleep a guessed constant.
    deadline = time.time() + 60
    while time.time() < deadline:
        found = _search('{ name = "agent.run_case" }', window=300)
        if found:
            spans = _spans(found[0]["traceID"])
            if len({s["service"] for s in spans}) > 1:
                _CACHE["spans"] = spans
                return spans
        time.sleep(3)
    pytest.fail("no cross-service trace arrived at Tempo within 60s")


def test_the_agent_span_is_the_root_of_the_trace(s1_trace):
    roots = [s for s in s1_trace if s["parent"] is None]

    assert len(roots) == 1, f"expected one root span, got {roots}"
    assert roots[0]["service"] == "agent"


def test_one_trace_spans_more_than_one_service(s1_trace):
    """The property the documents claim. Without a root span in the agent, each
    service starts its own trace and the per-service traces all look fine."""
    services = {s["service"] for s in s1_trace}

    assert len(services) > 1, f"the trace never left one service: {services}"
    assert "agent" in services


def test_every_span_in_the_breaching_run_reports_success(s1_trace):
    """The finding, measured against a real collector.

    S1 ends with the aggregate breached. If any span here were red, the breach
    would have been visible to ordinary monitoring and there would be no
    finding -- the whole claim is that a completely healthy trace accompanies
    incorrect business state.
    """
    errored = [s for s in s1_trace if s["status"] in (2, "STATUS_CODE_ERROR")]

    assert not errored, f"expected an all-green trace, these reported errors: {errored}"
