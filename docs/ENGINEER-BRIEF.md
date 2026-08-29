# Engineer Brief — Stage 0

## WHAT

A harness that drives two independently-owned services into a scripted
interleaving and returns a trustworthy verdict on an aggregate money invariant
(`refunds + credits ≤ authorized_compensation`) that spans both, where neither
service can see the sum.

It exists to answer one question about itself: **can this rig produce a known
violation on demand, refuse to produce one when it shouldn't, and replay
identically?** All five schedules are controls. None is a finding.

## WHY THIS APPROACH

**Rejected: assert on task success.** Conventional agent metrics report whether
the agent completed its task. Both actors here complete successfully and the
business state is still wrong. Task success cannot see the failure.

**Rejected: a single service with a CHECK constraint.** That has one transaction
boundary, so the database enforces the invariant and there is nothing to study.
Making the ceiling a Billing column would have collapsed the experiment the same
way — Billing would be authoritative for the aggregate.

**Chosen: two independently-owned databases, no shared transaction, with a
deterministic barrier.** The barrier is what separates this from chaos testing:
a violation that only appears sometimes proves nothing, because it cannot be
told from scheduling luck.

## HOW

**Actor identity is a wire value.** A checkpoint inside a service cannot derive
the actor from the runtime — pid, thread id, task id and contextvars all
identify the *server's* unit of work, not the caller. Two actors traverse the
same handler. Identity arrives as `X-Actor-Id` and is bound at ingress.

**The barrier key is a 4-tuple** `(schedule, actor, checkpoint, occurrence)`, and
the coordinator assigns the occurrence itself so clients hold no counter state.
P3's retry arrives in a fresh request context where any client-side counter
would reset to zero.

**It fails closed.** Missing header, unknown actor, undeclared occurrence → abort
and dump every waiter. A default-releasing barrier manufactures results.

## TRADE-OFFS

- **~2s per schedule run.** Real sockets, real multi-worker servers, real
  Postgres. An in-process test client would be far faster and would serialise
  the actors, making every concurrency test pass for the wrong reason.
- **Duplicated schema knowledge in the oracle.** Deliberate. If the oracle
  imported the services' models, a bug would appear in both the system and its
  judge and cancel out invisibly.
- **Three Postgres containers.** The control service needs its own store or the
  ceiling ends up owned by a participant.
- **Coordinator is single-worker and holds state in memory.** It owns the
  schedule pointer and parked waiters; a second worker would hold a second,
  divergent barrier. If it ever needs to scale, that state moves to a store
  first.

## NEXT ENGINEER

**Four things you must know before touching this.**

1. **If P2 stops violating, the rig is broken — not the thesis.** Check in
   order: barrier placement relative to commit, actor scoping, server worker
   count, oracle correctness, DB isolation level.

2. **If P4 replays diverge, stop everything.** Determinism failing invalidates
   the method itself; every verdict becomes unreproducible. It is also the
   failure most tempting to dismiss as flakiness. It is not flakiness.

3. **Release order is not execution order.** The barrier orders *releases*. It
   does not determine which actor reaches a shared service first after being
   released. This silently broke P0 — the reservation winner was decided by
   scheduling luck. Anywhere two actors race to the same service, add an
   explicit checkpoint.

4. **Green means nothing until you have mutated it.** Four defects were shipped
   into this repo and every one was caught by mutation, never by tests passing:
   a racy assertion, dropped decision-log writes that 60 tests missed, a
   no-retry test that passed at `retries=0` *and* `retries=3`, and a violation
   claim that still passed with the barrier entirely bypassed. Before believing
   any load-bearing assertion, break the thing it guards and watch it fail.

**Adding a schedule:** declare every checkpoint the actors will reach, including
occurrences. An undeclared one aborts the run — that is the design, not a bug.
Couple any verdict assertion to `assert_schedule_executed`, or the verdict is
not attributable to the schedule.

**Adding a table:** add it to `truncate_all()`. `test_reset_covers_every_table_that_exists`
enumerates `pg_tables` and will fail if you don't — that check exists because a
forgotten table is how a reset rots, and leftover rows are indistinguishable
from a real violation.
