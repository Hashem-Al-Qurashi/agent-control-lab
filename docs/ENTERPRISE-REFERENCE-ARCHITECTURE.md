# Enterprise Reference Architecture

What this lab is a scale model of, and what a real deployment needs that the lab
does not have.

Read it as a **map from a measured finding to a production topology**, not as a
recommended stack. The finding is architectural, so the response has to be too:
`S1` breaches an aggregate while every local control holds, and no amount of
better agents, better prompts or better monitoring changes that.

---

## The shape of the problem

```
                    ┌──────────────────────────────┐
                    │   agent (any cognition)      │
                    └──────────────┬───────────────┘
                       reads       │      acts
              ┌────────────────────┴──────────────────┐
              ▼                                       ▼
   ┌────────────────────┐              ┌──────────────────────────┐
   │ read model / CRM   │              │ services that own effects│
   │ projection         │              │  billing · ledger · …    │
   └─────────▲──────────┘              └────────────┬─────────────┘
             │        events (async, lagging)       │
             └─────────────────────────────────────┘
```

The agent decides from the left box and acts on the right. **The gap between them
is where the money goes wrong**, and it is a property of the topology, not of the
agent — which is why `S1` violates with a strictly sequential schedule and no
concurrency at all (`test_s1_violates_even_though_the_actors_never_overlap`).

## Five planes

| Plane | Answers | In the lab | A production deployment adds |
|---|---|---|---|
| **Cognition** | what to do | deterministic policy (ADR-011) | model, tools, orchestration |
| **Identity** | who is asking | signed tokens | OIDC issuer, short TTLs, rotation (ADR-005) |
| **Authorization** | may this action proceed | per-service policy check | central policy service, audit trail |
| **Coordination** | may this action proceed *given every other one* | reservation authority | the plane most systems do not have |
| **Evidence** | what actually happened | decision log, oracle, reconciler | traces, invariant checks, retention |

**The coordination plane is the contribution.** The other four are standard and
most competent teams build them. `S6` shows authorization working exactly as
intended and the aggregate breaching anyway.

---

## The coordination plane

Everything that makes it work, and each thing that makes it fail if omitted.

**It must see all of an invariant's inputs at decision time.** That is the whole
requirement, and it is what a per-service check structurally cannot do. A `CHECK`
constraint cannot read another database (ADR-009).

**Authority is granted before the action, not validated after.** A hold is taken,
then the effect is written, then the hold is committed. Validating afterwards
detects a breach that already happened.

**The check and the grant are one atomic step.** Serialised per case by an
advisory lock. Split them and the coordination service contains the very
read-check-write race it exists to prevent — a silent and deeply ironic defect.
`test_the_ceiling_holds_under_contention` holds it to exactly ten grants and
exactly $1,000 at 100 concurrent agents.

**Holds are released when their action fails**
(`test_a_failed_action_releases_its_hold`), **committed holds cannot be released**
(`test_committing_a_released_hold_is_refused`), and release is idempotent.

**Refusal is a 409, never a 500.** An agent cannot distinguish *"you may not"*
from *"try again later"*, and a refusal that looks like an outage will be retried
(`test_refusals_are_refusals_not_errors`).

**Scoping is per invariant, not per service.** The lock is keyed on the case, so
contention is per-case and unrelated work does not queue (`CAPACITY.md`).

### What it costs, stated plainly

A serialisation point, and latency that scales linearly with contention on one
case. That is not an implementation shortcut to be optimised away — it is the
mechanism. The alternatives in `CAPACITY.md` trade exactness for throughput, and
exactness is the property being bought.

### When you do not need one

Most invariants are local, and a local invariant enforced by a database
constraint is the right answer. `INVARIANT-CATALOG.md` exists to tell them apart:
the taxonomy decides where enforcement can live, and only cross-service hard
invariants need this plane. **Adding a coordination authority for a local
invariant is a serialisation point bought for nothing.**

---

## The evidence plane

`S1` and `S3` produce a **clean reconciliation report and wrong money**. Lag,
drift, duplicates and orphans are all absent, because none of those is what went
wrong (`test_a_fully_caught_up_breach_produces_no_findings_at_all`).

So the plane splits in two:

- **Operational health** — is the machinery working? Lag, retries, error rates.
- **Invariant checking** — is the business state correct? A separate query, over
  data the services do not share, run at a quiescence gate.

**A system with excellent observability and no invariant checker cannot detect
this class of breach.** That is measured here, not argued. Whatever alerts on the
second must be able to read across service boundaries, which makes it an
architectural component with its own credentials — read-only, and writing its own
queries so a shared bug cannot cancel out (T10, T11).

---

## Deliberately absent, each with its reasoning

| Component | Status | Why |
|---|---|---|
| Kafka | outbox instead | determinism vs broker internals — ADR-010 |
| LangGraph / any framework | plain Python | no model in the tested arm; known tool-node anomalies — ADR-011 |
| Temporal / durable execution | not built | triggers named rather than adopted — ADR-006 |
| OIDC issuer, token rotation | not built | tokens are signed but immortal — ADR-005, T1 |
| OTel collector, Grafana | spans only | traces are emitted and joined; nothing collects them |
| LLM arms (C, D) | blocked | credentials — ADR-008 |

Named rather than omitted, so their absence is a decision and not an oversight. A
reader who needs one of them knows exactly which claim it would strengthen.

---

## Adopting this without adopting the lab

The order matters, because the first step is the one that tells you whether the
rest applies:

1. **Write the invariants down and classify them.** Most teams have never
   enumerated them. `INVARIANT-CATALOG.md` is the format; the taxonomy decides
   where each can be enforced.
2. **For each cross-service hard invariant, name its authority.** If the answer
   is "each service checks its own part", that invariant is unenforced, and the
   gap is the finding.
3. **Measure your own exposure window.** `MODE-B.md` shows it is bounded by the
   agent's read-check-write duration and by arrival separation — both measurable
   in production with no harness at all.
4. **Add coordination only where step 2 found a gap.** Not everywhere.
5. **Check invariants separately from operational health**, or the failure stays
   invisible exactly as it does here.

Step 1 is free and frequently sufficient to end the discussion — either every
invariant is local, in which case none of this applies, or one is not, and it has
no authority.
