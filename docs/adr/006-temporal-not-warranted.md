# ADR-006 — Durable execution is not warranted by the evidence

**Status:** accepted · **Date:** 2026-08-29

## Context

`LAB-BUILD.md` lists Temporal for Stage 2, with an explicit condition attached:

> **Temporal enters only if reservations alone prove insufficient** — for durable
> execution, activity retries, workflow recovery, timers, compensation.

That condition has now been tested rather than assumed.

## Evidence

Reservations were applied to both failure modes, which are different in kind:

| Schedule | Failure mode | Without reservation | With reservation |
|---|---|---|---|
| P2 → P0 | Concurrency race — both actors read before either wrote | VIOLATION $1,100 | **CLEAN** |
| S1 → S1H | Staleness — B reads strictly *after* A committed, from a lagging view | VIOLATION $1,100 | **CLEAN** |

S1H is the stronger result. A test asserts B's projection was *exactly as stale
as in S1* — zero events applied before it read — and the outcome is still
correct. The reservation works because the control service holds **authoritative**
state rather than a derived view.

Compensation, the other capability Temporal was listed for, is implemented and
tested directly: a failed action releases its hold, a successful one commits it,
release is idempotent, a committed hold cannot be released and a released one
cannot be committed.

## Decision

**Do not add Temporal.** The stated condition is not met.

Adding it now would enlarge the repo without making any finding more
trustworthy — the repo's own stated principle, and the same reasoning that
already excluded Kubernetes, a React dashboard, and five LLM providers.

## What would change this

Temporal earns its place the moment any of these appears, and none is
speculative — each is a real gap in what exists today:

1. **A workflow that must survive process death mid-sequence.** Reservations
   protect the *aggregate*; they do not resume a half-finished sequence of
   actions. Today a crashed agent leaves a held reservation that a reaper must
   clean up, not a workflow that continues.
2. **Timers.** A hold that must expire after N minutes without an external
   scheduler. Currently nothing expires holds.
3. **Multi-step compensation.** Today one action maps to one hold. A sequence of
   three effects needing ordered rollback is a saga, and hand-rolling one is
   exactly the wrong place to be clever.

## Honest limitation of this ADR

This tests reservations against *two* failure modes at *one* level of
concurrency, in a harness whose schedules are deliberately deterministic. It is
evidence that reservations are sufficient **here**, not a general claim that
durable execution is unnecessary for action-taking agents.

A production system with genuine crash recovery, long-running workflows, or
multi-step compensation should expect the answer to differ — and the three
triggers above are where to look for it.
