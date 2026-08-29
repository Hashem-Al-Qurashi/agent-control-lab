"""Spans have to leave the process, or the trace nobody can open is prose.

libs/tracing.py says the traces are real and that a reviewer opening S1 sees a
clean distributed transaction. That was true of the span objects and false of
the deployment: no TracerProvider was ever installed outside tests, so every
span in a running service went to the no-op default and nothing collected it.
"""

import libs.tracing as tracing


def _reset():
    tracing._EXPORT_CONFIGURED = False


def test_export_is_off_when_no_endpoint_is_configured():
    """Default off. A test suite that silently ships spans to a collector is
    slower, flakier, and dependent on a container nobody asked for."""
    _reset()

    assert tracing.configure_export("billing", endpoint=None) is False


def test_export_is_enabled_when_an_endpoint_is_configured():
    _reset()

    assert tracing.configure_export("billing", endpoint="http://localhost:4317") is True


def test_configuring_twice_installs_one_provider():
    """A second install would silently drop the first provider's spans.

    OpenTelemetry permits set_tracer_provider once per process and warns rather
    than failing, so a double call loses data without an error.
    """
    _reset()
    tracing.configure_export("billing", endpoint="http://localhost:4317")

    assert tracing.configure_export("billing", endpoint="http://localhost:4317") is False


def test_the_service_name_is_recorded_on_the_resource():
    """Without it every span in Grafana reads 'unknown_service' and the trace
    cannot be attributed to a service."""
    _reset()
    tracing.configure_export("ledger", endpoint="http://localhost:4317")

    resource = tracing.installed_resource()
    assert resource is not None
    assert resource.attributes["service.name"] == "ledger"


def test_every_service_configures_export_under_its_own_name():
    """A service that never calls configure_export emits to the no-op provider.

    Checked structurally: the failure is invisible at runtime -- spans are still
    created, the code still works, and nothing arrives at the collector.
    """
    import pathlib
    import re

    repo = pathlib.Path(__file__).resolve().parents[2]
    missing = []
    for name in ("billing", "ledger", "control", "crm", "entitlements"):
        source = (repo / "apps" / name / "main.py").read_text()
        if not re.search(rf'configure_export\(\s*"{name}"', source):
            missing.append(name)

    assert not missing, f"services that never configure span export: {missing}"
