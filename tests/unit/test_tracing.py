"""Stage 1: distributed tracing, and what it does not tell you.

Tracing is part of the baseline a competent team ships, and LAB-SPEC requires
the baseline's DETECTION to be competent or the silent-failure finding is
manufactured. So the traces here are real: one trace id spans the agent's
decision and every service call it caused, and each span carries the actor.

The point is what the trace shows afterwards. Every span succeeds. No error, no
exception, no retry, no anomalous latency. A reviewer opening the trace for the
S1 run sees a clean distributed transaction -- and the money is wrong.

That is the third green signal, alongside task success and reconciliation. Their
agreement is the finding.
"""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from libs.barrier.middleware import actor_identity, outbound_headers
from libs.tracing import current_traceparent, span, use_traceparent


# OpenTelemetry's global tracer provider can only be set ONCE per process --
# later calls are ignored. Installing a fresh provider per test therefore
# silently routed spans to the first test's exporter, and later tests saw zero
# spans. One provider, one exporter, cleared between tests.
_EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))
trace.set_tracer_provider(_PROVIDER)


@pytest.fixture(autouse=True)
def _clear_spans():
    _EXPORTER.clear()
    yield
    _EXPORTER.clear()


def _recording_tracer():
    return _EXPORTER


def test_a_span_records_the_actor():
    exporter = _recording_tracer()

    with actor_identity("A", "S1"):
        with span("agent.decide"):
            pass

    spans = exporter.get_finished_spans()
    assert spans[-1].name == "agent.decide"
    assert spans[-1].attributes["acl.actor_id"] == "A"
    assert spans[-1].attributes["acl.schedule_id"] == "S1"


def test_traceparent_is_carried_on_outbound_calls():
    """Identity and trace context travel together, or the trace fragments at
    the first service boundary and stops being distributed at all."""
    _recording_tracer()

    with actor_identity("A", "S1"):
        with span("agent.decide"):
            headers = outbound_headers()

    assert "traceparent" in headers
    assert headers["X-Actor-Id"] == "A"


def test_a_downstream_span_joins_the_same_trace():
    """The property that makes it one trace rather than several."""
    exporter = _recording_tracer()

    with actor_identity("A", "S1"):
        with span("agent.decide"):
            carried = current_traceparent()

    # A different process receiving that header continues the same trace.
    with use_traceparent(carried):
        with actor_identity("A", "S1"):
            with span("billing.create_refund"):
                pass

    spans = exporter.get_finished_spans()
    trace_ids = {s.context.trace_id for s in spans}
    assert len(trace_ids) == 1, (
        f"spans landed in {len(trace_ids)} traces -- the trace fragmented at the "
        "service boundary"
    )


def test_spans_report_success_when_nothing_errored():
    """The finding, in miniature.

    A locally-correct action on stale data produces a completely healthy trace.
    Nothing here is broken, which is exactly why tracing cannot see the breach.
    """
    exporter = _recording_tracer()

    with actor_identity("B", "S1"):
        with span("agent.decide"):
            with span("crm.read_compensation"):
                pass
            with span("ledger.create_credit"):
                pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 3
    for s in spans:
        assert s.status.is_ok or s.status.status_code.name == "UNSET", (
            f"{s.name} reported {s.status.status_code} -- the S1 trace must be "
            "clean, or the silent-failure claim does not hold"
        )
        assert s.events == (), f"{s.name} recorded an event; expected none"


def test_an_actual_failure_is_recorded():
    """Tracing must still catch real failures, or its silence proves nothing."""
    exporter = _recording_tracer()

    with actor_identity("A", "S1"):
        try:
            with span("billing.create_refund"):
                raise RuntimeError("service unavailable")
        except RuntimeError:
            pass

    failed = exporter.get_finished_spans()[-1]
    assert failed.status.status_code.name == "ERROR"
    assert failed.events, "an exception should have been recorded on the span"
