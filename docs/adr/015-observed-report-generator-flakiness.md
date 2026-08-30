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


---

## Update — 2026-08-30: likely the same defect as ADR-007

ADR-007 has now reproduced its divergence under active concurrent database
access, and failed to reproduce it under idle co-tenancy. This ADR'''s symptom
fits that condition exactly: it appears only in the multi-schedule generator --
the one place where schedules run back-to-back against shared databases with
truncation between them -- and never when a schedule runs alone.

The review that produced this hypothesis suggested both ADRs might be one defect
with two presentations. ADR-007'''s reproduction supports that, and points at the
same place: whatever active database concurrency does to checkpoint ordering.

Still open, and now more likely to close together than separately.


---

## Update — 2026-08-30 (second): the shared cause is truncation, not concurrency

ADR-007'''s captured diff identified the mechanism behind its divergence: a
process truncating the tables between a run and its fingerprint read empties
decision_log, which the determinism test reports as a divergence. The barrier'''s
release order was identical throughout.

This ADR'''s symptom is the sibling of that. The report generator truncates all
four databases **between** schedules, and its failures are always a projector'''s
final checkpoint appearing not to have run. Both are the same class: a
measurement reading mutable state that something else has cleared, reported as a
property of the system under test.

The one-defect hypothesis therefore holds, with the cause named more precisely
than concurrency: **truncation racing a read that is not part of the run it
describes.**

Still open, and now with a concrete thing to fix in both places rather than a
mystery to reproduce.


---

## Update — 2026-08-30 (third): ADR-007 closed, and this one likely with it

ADR-007 is resolved. The barrier never diverged across roughly 700 replays,
several hundred of them under active concurrent truncation. Every divergence it
ever recorded was the measurement losing its evidence, and the determinism suite
now reports `CorruptSample` instead of a false finding.

This ADR's symptom is the same shape one layer up: the report generator
truncates all four databases between schedules, and its failures are always a
projector's final checkpoint appearing not to have run — a read describing a run
it was not part of.

The same remedy applies and has **not** been implemented here.
`assert_schedule_executed` should distinguish *"this schedule did not execute"*
from *"the record of its execution was cleared underneath it."* Until it does
this stays open — but as a known instrumentation gap with a named fix, not a
mystery.


---

## Update — 2026-08-30 (fourth): the previous update was wrong

The third update said this ADR shared ADR-007's cause — a read describing a run
it was not part of, with the record "cleared underneath it." **That is false and
is retracted.**

`assert_schedule_executed` compares `outcome.release_order`, and `release_order`
is a plain Python list living in the coordinator process
(`apps/coordinator/barrier.py`). Truncating Postgres cannot empty it. The
mechanism I attributed to this ADR is not reachable, and I asserted it because it
was a satisfying parallel to a finding I had just made — not because I had traced
the path.

### What is now ruled out, with evidence

**Cross-schedule leakage of `release_order`.** The obvious candidate, since the
report generator runs every schedule against one coordinator: `reset_state()`
sets `_barrier = None`, so `/declare` builds a fresh `Barrier` with an empty
`_release_order`. State cannot carry between schedules this way.

### What remains

The failures always involve a **projector** actor's final
`crm.before_apply_event`, never an agent's checkpoint. A projector reaches that
checkpoint only when it has an unapplied event to apply. So the live question is
narrow and stated as a question rather than an answer:

> Under what conditions does the projector find nothing to apply in a
> multi-schedule run, when it always finds something in an isolated one?

**No fix is implemented here**, deliberately. The proposed one — distinguishing
"did not execute" from "record cleared" — targets a state that cannot occur, and
implementing it would have added a check that could never fire. That is the
fix-reachability failure `/strict`'s pre-flight check exists to catch, and it
caught it.

### Status

Open, and now honestly scoped. Not "same cause as ADR-007" — that was wrong. The
next step is instrumenting the projector's emit path independently of
`release_order`, to establish whether the checkpoint was **never emitted** or
**emitted and unrecorded**. Those are different defects and nothing here
currently distinguishes them.
