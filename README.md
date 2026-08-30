# Agent Control Lab

A reproducible harness that drives independently-owned services into scripted
interleavings and returns a trustworthy verdict on an aggregate money invariant.

```
sum(refunds) + sum(credits)  ≤  authorized_compensation
```

Billing owns refunds. Ledger owns credits. Separate databases, no shared
transaction boundary — neither can see the sum. CRM holds a *projection* of the
total, which is what an agent is usually given to read. A control service can
hold reservations against the budget.

**The result in one line:** three of eleven scenarios end with the business state
wrong, and two of those are invisible to every signal the system emits — while
every action was authenticated, authorized, idempotent, and individually
correct.

## The two failure modes

**P-series — concurrency.** Two agents read before either writes. Textbook
read-then-write, known since Gray. Nothing here is claimed as novel.

**S-series — staleness.** The interesting one. Agent B reads *strictly after* A
has committed and been acknowledged, and is wrong anyway, because it reads a
projection that has not caught up. **Sequencing does not fix this**, which is
what separates it from the P-series.

| Schedule | Verdict | Role |
|---|---|---|
| **P1** | CLEAN | Sequential. Proves the oracle is not trigger-happy |
| **P2** | **VIOLATION** | Concurrency race. Positive control |
| **P0** | CLEAN | P2's interleaving + reservation. Locates the fault in the interface |
| **P3** | CLEAN | Lost ACK + keyed retry. Idempotency is orthogonal to the aggregate |
| **S1** | **VIOLATION** | Strictly sequential, stale view. Sequencing does not fix it |
| **S1C** | CLEAN | S1 with the projection caught up. Isolates the variable |
| **S1H** | CLEAN | S1 with a reservation. Coordination fixes staleness too |
| **S3** | **VIOLATION** | Partial catch-up. Exposure tracks the lag |
| **S4** | CLEAN | Reversed apply order. Rules out ordering as the cause |
| **S5** | CLEAN | At-least-once redelivery. Projection must not inflate |
| **S6** | CLEAN | Above threshold, no approval. Authorization is not decorative |

Plus **P4**, which replays every schedule and requires byte-identical transition
sequences.

**If P2 or S1 stops violating, the rig is broken — not the thesis.** Check
barrier placement relative to commit, actor scoping, worker count, oracle
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

**S1 is the finding.** No overlap at all — B begins only after A is fully
acknowledged. It reads the CRM projection, because that is the integration point
it was given, and the projection has not applied A's event. The remedy is *not* a
faster projection; a faster projection is still a projection. S1H shows what
works: an authority that holds real state rather than a derived view.

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

## Documents

| Document | What it is |
|---|---|
| [RESULTS.md](docs/RESULTS.md) | Every verdict, **generated by the run that asserts it** |
| [ASSESSMENT-SAMPLE.md](docs/ASSESSMENT-SAMPLE.md) | This repo assessed as if it were a client system |
| [INVARIANT-CATALOG.md](docs/INVARIANT-CATALOG.md) | The invariants, and the taxonomy that decides how each can be enforced |
| [THREAT-MODEL.md](docs/THREAT-MODEL.md) | T1–T12, every control citing a test that exists |
| [MODE-B.md](docs/MODE-B.md) | Naturalistic stress: exposure vs arrival separation, and why a bare frequency is uninterpretable |
| [CAPACITY.md](docs/CAPACITY.md) | The ceiling holds exactly at 100 concurrent agents; latency scales linearly, and why |
| [READINESS-MODEL.md](docs/READINESS-MODEL.md) | Ten domains, each citing what this lab measured — including where it held and still wasn't enough |
| [RUNBOOKS.md](docs/RUNBOOKS.md) · [SLOS.md](docs/SLOS.md) · [INCIDENT-001.md](docs/INCIDENT-001.md) | Operations: one runbook per alert that can fire, objectives split from zero-tolerance invariants, and a worked incident from this build |
| [WHITESTONE-ASSESSMENT-SAMPLE.pdf](docs/WHITESTONE-ASSESSMENT-SAMPLE.pdf) | The assessment as a client would receive it — `make assessment-pdf` rebuilds it |
| [visual/diligent-agent.html](docs/visual/diligent-agent.html) | Interactive walkthrough of the interleaving — pinned to the measured results by a test |
| [LLM-ARMS.md](docs/LLM-ARMS.md) | Arms C and D: the violation reproduces with a real model 5/5, and the control holds it 5/5 |
| [DEEP-DIVE.md](docs/DEEP-DIVE.md) | The 20-minute argument, with the instrument defended before the results and the hard questions answered |
| [PRIOR-INCIDENTS.md](docs/PRIOR-INCIDENTS.md) | Four documented incidents read at primary source — with what each does *not* support, and what was rejected |
| [DEMO.md](docs/DEMO.md) | The 10-minute walkthrough, in order, with every command verified |
| [OBSERVABILITY.md](docs/OBSERVABILITY.md) | Tempo + Grafana, and the defect where the library was tested and the system was uninstrumented |
| [ENGINEER-BRIEF.md](docs/ENGINEER-BRIEF.md) | What the next person must know before touching this |
| [ENTERPRISE-REFERENCE-ARCHITECTURE.md](docs/ENTERPRISE-REFERENCE-ARCHITECTURE.md) | Five planes, what the coordination plane costs, and how to adopt it without adopting this repo |
| [adr/](docs/adr/) | Fourteen decisions, including six things deliberately *not* built |

Citations are enforced, not trusted: `tests/unit/test_docs_integrity.py` fails if
a document names a test, schedule, ADR, or `make reproduce` target that does not
exist.

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

**Temporal** — ADR-006 records why: reservations are sufficient for both failure
modes, and the ADR names the three triggers that would change that.

**Keycloak and OPA** — ADR-005 records the substitution. The *properties* they
provide are implemented and tested; the products are not running, and the exact
diff is written down.

**Kafka, LLM agents, naturalistic stress mode, cloud deployment** — later stages.

Adding any of them now would enlarge the repo without making a single finding
more trustworthy.
