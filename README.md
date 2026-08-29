# Agent Control Lab — Stage 0

A reproducible harness that drives two independently-owned services into a
scripted interleaving and returns a trustworthy verdict on an aggregate money
invariant.

```
sum(refunds) + sum(credits)  ≤  authorized_compensation
```

Billing owns refunds. Ledger owns credits. They have separate databases and no
shared transaction boundary, so neither can see the sum.

## What Stage 0 is, and is not

**It is instrument validation.** Its job is to prove the rig can deterministically
produce a *known* violation, refuse to produce one when it shouldn't, and
demonstrate the contrast.

**It is not a finding.** With two authoritative services and no propagation lag,
the only reachable failure is plain read-then-write TOCTOU — textbook, known
since Gray. Nothing here claims otherwise. The interesting case, where an agent
reads every authoritative source and *still* works from a stale cross-system
picture, needs event-driven projections and belongs to a later stage.

Every schedule below is a control.

| Schedule | What it does | Required |
|---|---|---|
| **P0** | P2's exact interleaving, plus a reservation primitive | **PASS** |
| **P1** | Fully sequential, reads and writes both gated | **PASS** |
| **P2** | Concurrent read-check-write race | **FAIL — violation** |
| **P3** | Commit, lost acknowledgement, explicit keyed retry | **PASS** |
| **P4** | Every schedule replayed N times | **PASS — identical** |

**If P2 does not violate, the rig is broken — not the thesis.** Check barrier
placement relative to commit, actor scoping, server worker count, oracle
correctness, and DB isolation level, in that order.

## Run it

```bash
make up                        # three postgres containers
make reproduce SCHEDULE=P2     # the violation: 1100 against a 1000 ceiling
make reproduce SCHEDULE=P0     # same interleaving, coordinated, stays clean
make determinism               # 20 replays, identical transition sequences
make test                      # everything
```

## Why each control exists

**P2 is a positive control.** Two actors read every authoritative system, both
decide correctly from what they observed, both actions are authorised,
idempotent, locally valid and successfully executed. The aggregate is 1100.
Nothing is claimed from this beyond: the rig can produce a known violation on
demand.

**P0 is what makes P2 mean anything.** Without it the rebuttal lands — *"you
built a system with no coordinator and then showed it doesn't coordinate."* P0
runs the identical schedule with a control service that can see the aggregate,
and the same diligent policy does not breach. That locates the failure in the
**interface the agent was given**, not in the agent's diligence.

**P3 is the anti-strawman control.** It proves the baseline is not rigged to fail
everywhere: local mechanisms work exactly where they should. It also
demonstrates — rather than asserts — that idempotency is *orthogonal* to the
aggregate invariant. Idempotency stops one operation being applied twice; the
aggregate is breached by two *different* valid operations. "Just add idempotency
keys" is not a fix for P2, and P3 is the evidence.

**P1 proves the oracle is not trigger-happy.** If it reports a violation, the
instrument is wrong and every other verdict is worthless.

**P4 guards the anomaly that invalidates everything.** If replays diverge, no
verdict is reproducible and a violation cannot be told apart from scheduling
luck. It is also the failure most tempting to dismiss as flakiness.

## How determinism is achieved

Actor identity is a **wire value** (`X-Actor-Id`, `X-Schedule-Id`). A checkpoint
inside a service cannot derive the actor from the runtime — pid, thread id, task
id and contextvars all identify the *server's* unit of work, not the caller.

The barrier key is the 4-tuple `(schedule_id, actor_id, checkpoint, occurrence)`.
The coordinator assigns the occurrence index itself, so clients hold no counter
state — necessary for P3, where the retry arrives in a fresh request context.

The barrier **fails closed**. A missing header, unknown actor, or undeclared
occurrence aborts the run and dumps every waiter. It never default-releases,
because a default-releasing barrier manufactures results.

**Release order is not execution order.** Releasing two actors in a known order
does not determine which reaches a shared service first. Anywhere that matters,
there is an explicit checkpoint.

## What guards the result

- **Oracle calibration** runs before any schedule. It plants a known violation
  and a known-safe state and refuses to proceed unless both are judged
  correctly. Unproven instrumentation would taint every verdict.
- **The oracle cannot write.** Its role has `INSERT/UPDATE/DELETE` revoked.
- **The oracle imports no service code.** Enforced by AST. A shared bug would
  otherwise appear in both the system and its judge and cancel out invisibly.
- **Quiescence before evaluation.** Two independent Postgres admit no
  cross-database snapshot, so reading mid-flight yields a torn state.
- **Duplicate idempotency keys ⇒ INCONCLUSIVE, never VIOLATION.** One decision
  producing two effects is a rig defect, and reporting it as a violation would
  be the most damaging false positive available — it has the exact shape of the
  result being claimed.
- **Multi-worker services, proven by distinct pids.** A single worker serialises
  the actors, P2 becomes P1, and that reads as the thesis being false.
- **Genuine overlap asserted server-side**, not merely client-side.
- **Money is `Decimal`/`NUMERIC(12,2)` end to end.** Never float.

## Layout

```
apps/coordinator   barrier: schedule, occurrence, leases, faults, fail-closed
apps/billing       refunds        (own database)
apps/ledger        credits        (own database)
apps/control       reservations   (own database) — the P0 primitive
agents/diligent    policy, pooled processes, purity lint, clients
libs/barrier       actor-identity middleware, checkpoint client
oracle/            own SQL, invariants, calibration, quiescence, divergence
schedules/         P0–P3 declarations + runner
```

## Deliberately absent

Kafka · OIDC · OPA · OpenTelemetry · LangGraph · LLM agents · Temporal · a CRM
service · a reconciliation worker · naturalistic stress mode · cloud deployment.
All belong to later stages. Adding them here would enlarge the repo without
making the instrument more trustworthy.
