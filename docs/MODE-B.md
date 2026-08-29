# Mode B — naturalistic stress

Mode A answers *can this execution happen, and why*. It chooses the interleaving,
so it cannot answer *how often*. Mode B chooses nothing: two agents run
concurrently, no barrier, no schedule, and whatever happens happens.

Neither substitutes for the other. A Mode B frequency without Mode A cannot say
what caused anything. A Mode A counterexample without Mode B cannot say whether
it matters in practice.

## The first measurement was useless, and that was informative

40 runs, both agents launched simultaneously:

```
violations:    40/40 (100.0%)
window opened: 40/40 (100.0%)
```

100% is not a finding. At zero arrival separation the race window is open
essentially always, so the number describes the **workload**, not the system. A
frequency measured at exactly the worst case is not a frequency.

## Exposure against arrival separation

Varying how far apart the two agents *arrive* — a workload parameter, and
reported as the integrity rules require — turns one number into a curve. 10 runs
per point:

| Arrival separation | Violations | Window open |
|---:|---:|---:|
| 0 ms | **100%** | 100% |
| 50 ms | **100%** | 100% |
| 75 ms | **100%** | 100% |
| 100 ms | **20%** | 100% |
| 125 ms | 0% | 70% |
| 150 ms | 0% | 10% |
| 200 ms | 0% | 10% |

**The cliff sits between 75 ms and 125 ms**, and that is the actionable part: the
exposure window is the duration of the agent's own read-check-write sequence —
two reads plus a write against local services. Nothing exotic. Once the second
agent arrives after the first has committed, it sees the truth and declines.

For a real system the number will differ, and the *shape* is what transfers:
exposure is bounded by how long an agent's own sequence takes, and by how close
together agents arrive. Both are measurable in production without any of this
harness.

## Why the window observable earns its place

Look at 100 ms: the window was open in **100%** of runs, and only **20%**
violated.

An open window is **necessary but not sufficient**. The observable detects that
the second agent's read began before the first agent's write completed — the
*opportunity* for a stale read. A violation additionally requires the read to
actually miss the commit, and near the cliff it usually does not.

That distinction is exactly why a bare frequency is uninterpretable. Without the
observable, "0% at 125 ms" and "0% at 500 ms" look identical, when the first
means *the race had a chance and did not fire* and the second means *the race
never had a chance*. Only one of those is reassuring.

The 10% at 150–200 ms is the observable's noise floor: a read starting fractions
of a millisecond before an unrelated write ends. It never coincides with a
violation, which is the assertion the test makes —
`violations ≤ windows` at every point.

## Integrity

The ways this number could have been manufactured, and what prevents each:

- **No injected delay inside the system.** Nothing is paused mid-transaction, no
  checkpoint is held, and neither service behaves differently in Mode B than in
  Mode A. Arrival separation is *when the agents show up*, not what the system
  does. That line is what keeps Mode B from being Mode A wearing a disguise.
- **The oracle runs after each case, never during.** It cannot perturb what it
  measures.
- **Workload parameters are reported, not chosen quietly.** Two agents, amounts
  600 and 500, ceiling 1000, 10 runs per point, arrival separations as tabled.
- **A zero result is published.** The 0% rows are in the table.
- **Every run must return CLEAN or VIOLATION.** An `INCONCLUSIVE` would mean
  service idempotency broke and the frequency is not measuring what it claims.

## What this does not claim

Not a production estimate. One machine, local services, no network latency, two
agents, one case at a time. The frequency belongs to this workload and nothing
else.

What generalises is the shape: **exposure is a function of the agent's own
sequence duration and the arrival separation between agents** — and both of those
are things a real system can measure about itself.
