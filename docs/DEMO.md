# Demo script — 10 minutes

Every command here has been run. Timings are from an ordinary laptop with the
stack already up; `make up` on a cold machine adds about a minute for image
pulls.

The narrative has one job: **establish that the system is competent before
showing that it is wrong.** A demo that opens with the failure invites "you
built a broken system", and never recovers.

---

## 0 · Setup — before the recording starts

```
make up          # five Postgres containers, schemas created, health-gated
make calibrate   # the oracle proves itself before it is allowed to judge
```

`make calibrate` prints three lines. Say what they are, because everything
downstream depends on them:

```
planted_violation:      expected VIOLATION, got VIOLATION
planted_safe:           expected CLEAN,     got CLEAN
planted_voided_is_safe: expected CLEAN,     got CLEAN
```

> An oracle never shown to catch a planted violation, and never shown to pass a
> planted safe state, is unproven instrumentation. This runs before every
> schedule, not just here.

---

## 1 · The system is competent (2 min)

Open with what **works**, and let it be boring.

```
make reproduce SCHEDULE=S6      # ~11s
```

Both agents attempt. Both are refused. Nothing is written, no event published.

> Authorization is real. It stops what it is for. Hold that thought — the
> failure later is not authorization being absent or weak.

Name the rest without running them: signed tokens that expire, per-action
ceilings, tenant isolation as a hard deny, idempotent retries, atomic
effect-and-event, redelivery that does not double-count. Point at
`docs/THREAT-MODEL.md` — T1 to T12, every control citing a test.

---

## 2 · The failure (3 min)

```
make reproduce SCHEDULE=P2      # ~15s → VIOLATION, overage exactly $100
```

Two agents. Each reads every system available to it. Each correctly concludes
its action fits under the $1,000 ceiling. Both commit. The total is $1,100.

**Then close the obvious escape route immediately**, because the audience is
already thinking it:

```
make reproduce SCHEDULE=S1      # ~21s → VIOLATION, and nothing overlapped
```

> S1 is strictly sequential. Agent B starts reading *after* A has committed and
> been acknowledged. It is still wrong, because B reads a projection that has
> not applied A's event.

This is the pivot of the whole demo. If they take one thing away, it is that
**stopping the agents from overlapping does not fix it.**

---

## 3 · It is not the agent, and not the freshness (2 min)

```
make reproduce SCHEDULE=S1C     # identical, projection caught up → CLEAN
make reproduce SCHEDULE=S3      # projection PARTIALLY caught up → still VIOLATION
```

> S1C isolates one variable: whether the read model had caught up. Not the
> agent, not the ordering, not the amounts.
>
> S3 is the answer to "then make the projection faster." The third actor sees a
> **more current** view and the aggregate still breaks. Freshness narrows the
> window; it cannot close one that stays open until a write lands somewhere
> else.

---

## 4 · What does fix it (1 min)

```
make reproduce SCHEDULE=P0      # P2's interleaving + a reservation → CLEAN
make reproduce SCHEDULE=S1H     # S1's staleness + a reservation  → CLEAN
```

> Same interleaving, same staleness, same agent, same schedule. One control
> added. `S1H` asserts B's view was *exactly as stale as in S1* and the outcome
> was still correct.
>
> That pair locates the cause in the interface the agent was given, not in the
> agent.

Effort, if asked: about 150 lines and a table. The hard part is not the service
— it is deciding which operations count toward which limit, which no tool
answers for you.

---

## 5 · Why nobody would have noticed (2 min)

```
make observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4317 make reproduce SCHEDULE=S1
```

Open <http://127.0.0.1:3001> → **Agent Control Lab — traces**.

One trace: `agent` → `crm` → `ledger`. Three spans. **Zero errors.** The panel
for error spans is empty. The reconciler reports no lag, no drift, no
duplicates, no orphans.

> Every agent succeeded at its task. Every action was authorized. The trace is a
> clean distributed transaction. The reconciliation report is clean. And the
> money is wrong by $100.
>
> Three green signals agreeing, which is why this is not caught by adding more
> monitoring. Operational health and business correctness are different
> questions, and only one of them was being asked.

---

## Closing line

> Nothing here was a bug. No component failed. Every control did exactly what it
> was built to do, at the scope it was built for. The invariant spanned two
> services, and no authority owned it.
>
> The first step is not buying anything. It is writing your invariants down and
> asking, for each one, which system could enforce it. Most are local. The ones
> that are not usually have no owner, and that is the finding.

---

## If a question derails the demo

| Question | Answer |
|---|---|
| "Isn't this just a missing transaction?" | The services have separate databases — ADR-009. A `CHECK` cannot read another database. Merging them is the fix for a two-service system and does not survive the third. |
| "Wouldn't a smarter agent handle it?" | `S3`. It reads a fresher view and still breaks. |
| "Doesn't idempotency cover this?" | `P3` passes. Idempotency stops *one* operation applying twice; this is *two different valid* operations. Orthogonal. |
| "Is the baseline a strawman?" | `docs/adr/014-baseline-competence.md`, and the negative controls that pass: `P1`, `S1C`, `S4`, `S5`, `S6`. |
| "How often does this actually happen?" | `docs/MODE-B.md`. Do not quote a single frequency — show the curve and the cliff. |
| "Does it scale?" | `docs/CAPACITY.md`. Exactly ten grants and exactly $1,000 at 100 concurrent agents. |

## Do not do this in a demo

- **Do not run the full suite on camera.** It takes about four and a half
  minutes and shows nothing the individual schedules do not.
- **Do not claim a production frequency.** One machine, local services, no
  network latency. `MODE-B.md` states the limit; say it out loud.
- **Do not skip §1.** Showing the breakage before showing the competence is how
  the whole thing gets dismissed as a broken toy.
