"""Distributed tracing across the service boundaries.

Part of the baseline a competent team ships. LAB-SPEC requires the baseline's
DETECTION to be competent, or "the violation went undetected" is manufactured.
So the traces are real: one trace id spans the agent's decision and every call
it caused, and each span carries the actor.

What matters is what the trace shows for S1. Every span succeeds. No error, no
exception, no retry, no anomalous latency. A reviewer opening it sees a clean
distributed transaction while the money is wrong -- the third green signal
alongside task success and reconciliation.

W3C traceparent travels with actor identity on every outbound call. They are
propagated together deliberately: a trace that fragments at the first service
boundary is not distributed tracing, and identity without trace context cannot
be correlated afterwards.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)

_propagator = TraceContextTextMapPropagator()

# Installed at most once per process. OpenTelemetry permits set_tracer_provider
# once and then warns rather than failing, so a second call would silently drop
# the first provider's spans -- data loss with no error.
_EXPORT_CONFIGURED = False
_RESOURCE = None


def configure_export(service_name: str, endpoint: str | None = None) -> bool:
    """Install an OTLP exporter. Returns whether this call installed one.

    Off unless an endpoint is configured. A suite that silently ships spans to a
    collector is slower, flakier, and dependent on a container nobody asked for,
    so the default is no exporter and the no-op provider that implies.
    """
    global _EXPORT_CONFIGURED, _RESOURCE

    endpoint = endpoint if endpoint is not None else os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if not endpoint or _EXPORT_CONFIGURED:
        return False

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Without service.name every span reads "unknown_service" and a trace cannot
    # be attributed to the service that emitted it.
    _RESOURCE = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=_RESOURCE)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)
    _EXPORT_CONFIGURED = True
    return True


def installed_resource():
    """The resource attached to the installed provider, or None if export is off."""
    return _RESOURCE


def tracer():
    """Resolved at call time so tests can install a recording provider."""
    return trace.get_tracer("agent-control-lab")


@contextmanager
def span(name: str, **attributes) -> Iterator[trace.Span]:
    """A span tagged with the acting identity.

    Exceptions are recorded and re-raised. Swallowing here would make a real
    failure look like the clean trace S1 produces, and the whole point is that
    those two are distinguishable.
    """
    from libs.barrier.middleware import current_actor, current_schedule

    with tracer().start_as_current_span(name) as current:
        actor, schedule = current_actor(), current_schedule()
        if actor:
            current.set_attribute("acl.actor_id", actor)
        if schedule:
            current.set_attribute("acl.schedule_id", schedule)
        for key, value in attributes.items():
            current.set_attribute(f"acl.{key}", value)
        try:
            yield current
        except Exception as exc:
            current.record_exception(exc)
            current.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def current_traceparent() -> str | None:
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


@contextmanager
def use_traceparent(traceparent: str | None) -> Iterator[None]:
    """Continue a trace started in another process."""
    if not traceparent:
        yield
        return
    ctx = _propagator.extract({"traceparent": traceparent})
    token = otel_context.attach(ctx)
    try:
        yield
    finally:
        otel_context.detach(token)
