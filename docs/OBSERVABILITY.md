# Observability

`make observability` starts Tempo and Grafana. Then run any schedule with export
on:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4317 make reproduce SCHEDULE=S1
```

Grafana: <http://127.0.0.1:3001> → **Agent Control Lab — traces**.

Export is **off** unless that variable is set, so the suite and every published
result are unaffected by whether a collector is running.

---

## The defect this shipped with, and why it matters more than the stack

`libs/tracing.py` provided `span()`. `tests/unit/test_tracing.py` proved it
worked: spans carry the actor, a downstream span joins the caller's trace, a
failure is recorded as a failure. Nine tests, all green.

**Nothing in `apps/` or `agents/` ever called it.** No `TracerProvider` was
installed outside tests, so in a running service every span went to the no-op
default. Each service request began its own trace. The agent emitted nothing.

Meanwhile `THREAT-MODEL.md` and `READINESS-MODEL.md` both claimed *"one trace
spans the decision and every call it caused."* That was a description of a
library, presented as a property of a system.

It is the same defect this repository exists to describe, committed inside this
repository: **a green test covering a component, and the property it implies
about the whole absent.** The tests were not wrong. They were answering a
narrower question than the documents were asking.

One detail worth keeping. `test_traceparent_is_carried_on_outbound_calls` passed
throughout — because it created a span itself. In the real system
`current_traceparent()` had no active span to inject and returned `None`, so the
header was silently dropped. A neighbouring test asserted the forwarded headers
were *exactly* `{X-Actor-Id, X-Schedule-Id}` — an equality that was **pinning the
broken state**, and that failed the moment instrumentation was added.

## What is instrumented now

- **The middleware emits one server span per request**, joined to the inbound
  `traceparent`. Placed there rather than in each handler because a handler
  someone forgets to decorate produces no span and no error — the gap is
  invisible. Every request passes through the middleware.
- **The agent opens a root span** (`agent.run_case`) in its worker process, which
  spawns separately and so configures export itself.

## Verified against a real collector, not in memory

Every other tracing test uses an in-memory exporter — which is precisely what
stayed green while the system was uninstrumented. `tests/schedules/test_trace_export.py`
runs S1 with export on and queries Tempo:

| Assertion | Test |
|---|---|
| the agent span is the trace's only root | `test_the_agent_span_is_the_root_of_the_trace` |
| one trace covers more than one service | `test_one_trace_spans_more_than_one_service` |
| every span in the breaching run is green | `test_every_span_in_the_breaching_run_reports_success` |

Observed for S1: **one trace, `agent` → `crm` → `ledger`, three spans, zero
errors** — and the run's verdict is `VIOLATION`.

Confirmed non-vacuous by wiping Tempo's storage, asserting zero pre-existing
traces, and re-running: it still passes, so it is producing the trace rather
than matching a leftover one.

## What the dashboard is for

The panel titled *"Spans that reported an error"* is expected to stay **empty**
during S1. That is the finding, on screen: a clean distributed transaction over
incorrect business state.

Compare S1 with `S1H` — same staleness, plus a coordination authority. **The two
traces look alike.** Tracing shows what the system did, not whether it was
allowed to, which is why `READINESS-MODEL.md` scores observability and business
correctness as separate domains.

## Not built

Metrics and logs. No Prometheus, no Loki. The finding concerns whether a
*correct-looking* trace accompanies incorrect state, and traces answer that. A
metrics stack would enlarge the surface without making any claim here more
credible — and `LAB-BUILD.md`'s standing risk is that a component shipped at 60%
discredits the parts that are done.
