# INCIDENT-001 · The suite hung, and the hang hid the cause

**Date:** 2026-08-29 · **Severity:** high (development) · **Status:** resolved

A worked incident from this project, not a hypothetical. Included because the
useful part is not the fix — it is how long it took to notice anything was wrong.

## Timeline

| | |
|---|---|
| — | Full suite runs in ~2 minutes, routinely |
| T+0 | Suite started after adding per-actor scopes to the agent pool |
| T+2m | No completion. Assumed slow |
| T+10m | Still nothing. Assumed *very* slow |
| T+23m | Compared CPU time to wall clock: **0:35 of CPU over 23 minutes** |
| T+24m | Killed it; found 30 orphaned service processes |
| T+30m | Isolated to `test_p0.py`, which hung alone |
| T+35m | Root-caused, fixed, regression tests added |

**Detection took 23 minutes. Diagnosis took 12.**

## What happened

Two defects, stacked.

**First:** `dict.get(key, default)` returns the *value* when the key exists, even
if it is `None`. The runner always set `scopes`, so the default list never
applied and `None` reached `issue_token`.

**Second, and the real one:** that exception was raised while *setting up* the
job — before the job's own error handling. It killed the pool worker without
putting anything on the outbox, and `collect()` blocked forever.

## Why detection was so slow

Nothing was wrong from the outside. No error, no timeout, no log line. A hung
process and a slow process are indistinguishable until you look at CPU time, and
nothing prompted me to look for 23 minutes.

**A hang is strictly worse than a failure.** It burned the whole suite instead of
one test, and hid which schedule was broken.

## Contributing factor

The barrier already had leases, heartbeats, timeouts and waiter dumps — built
deliberately, because with work spread across processes silence and success look
identical from outside.

**The pool had none of it.** I built that machinery in one place and did not
apply it in the other, in the same codebase, within days.

## Corrective actions

| Action | Status |
|---|---|
| Wrap every pool job so nothing escapes without a result | done |
| Name the failing actor in the error | done |
| Regression test: a job whose setup cannot succeed surfaces as an error | done |
| Regression test: the pool serves the next job after a bad one | done |
| Guard against orphaned services at session start | done (ADR-007) |
| Runbook for the class | RB-004 |

## What this changed

The lesson is not "wrap your workers." It is that **a mechanism built for one
part of a system does not propagate to another by being nearby.** Leases existed
and were understood; the pool still shipped without an equivalent.

Wherever work crosses a process boundary in this repo, the question is now
explicit: *if this dies mid-job, does anything ever find out?*
