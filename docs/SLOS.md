# Service level objectives

Two kinds of target, and conflating them is the mistake this document exists to
prevent.

**Percentile objectives** describe speed and availability. Missing one is a
degradation: things are slow, users notice, you page someone.

**Zero-tolerance invariants** describe correctness. There is no percentage that
makes them acceptable, and averaging them destroys the information. "99.9% of
actions stayed in-tenant" describes a system that leaked data.

---

## Time-to-detect, and the value it cannot take

`oracle/detection.py` measures the delay between a breach landing and
reconciliation reporting it. For the aggregate breach that delay is **not a
number** — the reconciler never reports it, because nothing it checks is wrong
(`ACL-F19`).

**An undetected breach is never rendered as zero.** Averaged into a dashboard,
"0 seconds to detect" is the most flattering possible figure for the worst
possible outcome, and a mean detection time computed over cases that were never
detected is not a measurement of anything. `DetectionResult.summary()` returns
"never detected", and a test pins that it cannot be rendered as a delay.

The measurement is calibrated against a planted drift the reconciler does catch,
for the same reason the oracle is calibrated: an instrument never shown to
detect anything cannot be trusted when it detects nothing.


## Percentile objectives

Measured on this hardware; see `docs/CAPACITY.md` for method and limits.

| Objective | Target | Measured |
|---|---|---|
| Reservation decision, low contention (≤10) | p99 < 1s | 439 ms |
| Reservation decision, high contention (100 on one case) | p99 < 5s | 3,587 ms |
| Schedule run, end to end | p95 < 5s | ~1.2 s marginal |
| Verdict evaluation | p95 < 500ms | ~101 ms |

**Contention is per-case.** A hundred agents across a hundred cases do not queue;
a hundred on one case do. The high-contention row is a stress figure, not an
expected shape.

---

## Zero-tolerance invariants

Counted, never averaged. Any non-zero value is an incident.

| Invariant | Tolerance | How it is observed |
|---|---|---|
| Cross-tenant action committed | **0** | policy denies; a commit means the deny was bypassed |
| Unauthorized action committed | **0** | authorization precedes the transaction |
| Duplicate effect from one idempotency key | **0** | UNIQUE constraint; oracle returns INCONCLUSIVE |
| Committed total exceeds authorized | **0** | oracle at quiescence |
| Granted feature outside the current plan | **0** | E1 |
| Replay divergence for a declared schedule | **0** | P4 — a non-zero here invalidates every other number |

The last row is different in kind. The others mean *the system did something
wrong*. That one means *you can no longer tell whether it did*.

---

## Deliberately not an SLO

**Projection lag.** It is a real property with a real cost, but choosing its
bound is a business decision — how stale may an agent's view be before a decision
made on it is unacceptable? Mode B measured the exposure curve
(`docs/MODE-B.md`); it cannot choose the threshold.

Writing a number here that nobody agreed to would encode an engineering
assumption as a business commitment, which is exactly the failure the invariant
catalog warns about.

**Availability.** Not measured. One machine, local services, no redundancy. A
number here would be fiction.
