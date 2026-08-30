# ADR-015 — Intermittent `ScheduleNotExecuted` in the results generator

**Status:** OPEN · **Date:** 2026-08-30

## What was observed

While adding `S8` to `tests/schedules/test_results_report.py`, two consecutive
runs failed with `ScheduleNotExecuted` — **each on a different schedule**. First
`S5`, then `S3`. In both cases the missing step was the final projector
checkpoint (`crm.before_apply_event` at the highest occurrence):

```
declared: [... ('P', 'crm.before_apply_event', 1), ('P', 'crm.before_apply_event', 2)]
actual:   [... ('P', 'crm.before_apply_event', 1)]
```

The generator runs every schedule in one process against one stack, truncating
all four databases between them.

## What was ruled out

**`S8` did not cause it.** Removing `S8` from the list and running twice passed;
re-adding it and running again also passed. The failures are not a function of
the new entry.

`S3` and `S5` each pass consistently when run alone — five consecutive clean
runs across the two.

## What is suspicious and not established

Failing runs took **24–28s**; passing runs took **41–46s**. The faster runs are
the ones that failed, which is the opposite of what a timeout would predict and
is not yet explained. It suggests the failing runs did less work rather than ran
out of time — as if a projector found nothing to apply and its checkpoint was
therefore never reached.

That is a hypothesis with a mechanism, and **it has not been tested.**

## Why this is recorded rather than fixed

`assert_schedule_executed` is doing exactly what it exists for: refusing to
attribute a verdict to a schedule that did not run. The guard is working. What
is unknown is why the interleaving occasionally does not complete in the
multi-schedule generator when it always completes in isolation.

Papering over it — retrying, loosening the assertion, or widening the timeout —
would remove the signal without removing the cause, and this repository's
central claim is that a signal removed is worse than a failure observed.

## What would close this

- A reproduction with the projector's poll loop instrumented, showing whether it
  found zero unapplied events or was still waiting.
- Or a demonstration that state survives `truncate_all` between schedules —
  which would make this cross-schedule contamination and a genuine defect.

Until one of those, this stays **open**, alongside ADR-007. Two open
intermittencies is worth stating plainly: this harness is deterministic in
isolation and has not been proven deterministic in aggregate.
