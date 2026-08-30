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


# --- shared repo introspection -------------------------------------------
#
# test_docs_integrity and test_failure_catalog both need "which tests exist".
# A fixture rather than a duplicated helper: two copies of this drift, and the
# copy that drifts is the one that stops catching anything.

import pathlib  # noqa: E402
import re  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]


def _scan_defined_tests() -> set[str]:
    names = set()
    for path in (REPO / "tests").rglob("test_*.py"):
        names.update(re.findall(r"^def (test_[a-z0-9_]+)", path.read_text(), re.M))
    return names


def _scan_declared_schedules() -> set[str]:
    ids = set()
    for path in (REPO / "schedules").glob("*.yaml"):
        match = re.search(r"^schedule_id:\s*(\S+)", path.read_text(), re.M)
        if match:
            ids.add(match.group(1))
    return ids


@pytest.fixture(scope="session")
def defined_tests() -> set[str]:
    """Every test function name defined anywhere under tests/."""
    return _scan_defined_tests()


@pytest.fixture(scope="session")
def declared_schedules() -> set[str]:
    """Every schedule_id declared in schedules/*.yaml."""
    return _scan_declared_schedules()
