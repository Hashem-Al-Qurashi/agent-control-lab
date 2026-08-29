"""One recording tracer provider, shared by every unit test that inspects spans.

OpenTelemetry's global provider can be set ONCE per process; later calls are
ignored without error. Two test modules each installing their own therefore
means whichever imports first captures every span and the other sees an empty
exporter -- a failure that reads as "the code emits no spans."

test_tracing.py already carried that lesson as a comment. A second module
rediscovered it, which is why the provider now lives in one place that every
module reaches through a fixture instead of a convention each repeats.

It lives in conftest rather than a shared module because tests/ is not a
package: `from tests.unit.span_recorder import ...` raises ModuleNotFoundError.
"""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

_EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))
trace.set_tracer_provider(_PROVIDER)


@pytest.fixture
def spans():
    """The spans recorded during this test, cleared before and after."""
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()
