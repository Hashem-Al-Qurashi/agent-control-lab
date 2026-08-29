# ADR-012 — How the schedule controls execution, and where its authority stops

**Status:** accepted · **Date:** 2026-08-29

## The property being bought

Every Mode A claim has the form *"this execution produces this outcome."* That is
only a claim if the execution is reproducible. A violation appearing sometimes is
indistinguishable from scheduling luck, and proves nothing.

## Four decisions, each closing a specific failure

### 1. The coordinator assigns the occurrence index, not the client

The key is `(schedule_id, actor_id, checkpoint_name, occurrence_index)`, and the
client sends only the first three. The coordinator counts arrivals.

`P3` is why. A retry hits the same checkpoint a second time, in a fresh request
context where any request-scoped counter resets to zero — the retry would consume
the release token meant for the first attempt, and the deadlock would look like a
barrier bug rather than a counting bug. Server-side counting deletes the whole
class. Pinned by `test_second_arrival_at_same_checkpoint_gets_occurrence_1`.

### 2. Parked waiters block on a real event, never a poll loop

A poll loop wakes on its own timer, so release order is decided by scheduler
jitter, not by the schedule. The resulting non-determinism has the exact
signature of the race being studied — **it would look like the finding.**

Ordering is proven on the barrier alone, before any service exists:
`test_release_order_equals_declared_order_across_randomized_arrivals`.

### 3. Fail-closed, with no exception

Missing header, unknown actor, undeclared occurrence, wrong schedule id: abort
the run and dump every parked waiter. **No error path returns a release.**

The alternative — default-release on an unrecognised arrival — turns a harness
defect into a plausible-looking result, because the run completes and produces
numbers. `test_await_without_actor_header_is_400_and_aborts_the_run`,
`test_unknown_actor_is_400_and_aborts_the_run`,
`test_undeclared_occurrence_is_409_and_aborts_the_run`.

### 4. Leases, because a dead agent is silent

Agents are separate processes. One that dies parked at a barrier would hang the
suite forever; in-process it would have raised. Waiters heartbeat, and a lapsed
lease aborts the run with a dump — `test_waiter_that_is_never_released_times_out_with_a_dump`.

INCIDENT-001 is what this looks like when the mechanism is *absent*: the same
silence, in the process pool, cost 23 minutes to notice.

## The boundary — what the schedule does not control

**The schedule controls application-level checkpoints. It does not control
infrastructure internals.** Not Postgres lock acquisition, not TCP, not kernel
scheduling, not uvicorn's worker dispatch.

This is a deliberate limit, and it is what keeps the harness a measurement
instrument rather than a simulation. It also has a cost, stated plainly: **residual
non-determinism below the checkpoint layer is possible and is not eliminated by
anything here.** ADR-007 records an observed replay divergence that was never
reproduced and is still **open**.

## Verification, not assertion

Two guards, because determinism is the property most likely to be assumed:

- `test_schedule_replays_identically` — `ACL_REPLAYS` runs of each schedule must
  produce an identical transition sequence after normalising timestamps and ids.
- `assert_schedule_executed` — a violation claim is void if the barrier was
  bypassed. Five of six `P2` tests once passed with the schedule not running at
  all; the interleaving happened to occur anyway. **A green test is not evidence
  that the scripted execution is what produced the result.**
