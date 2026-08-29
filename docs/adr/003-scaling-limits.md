# ADR-003 — Measured scaling limits and what to fix first

**Status:** accepted · **Date:** 2026-08-29

## Context

Stage 0 is deliberately small. Stage 1 adds Kafka, OIDC, OPA, OpenTelemetry, a
third business service, LLM arms, ~15 schedules, and a naturalistic mode that
may run thousands of cases with the barriers off.

Guessing which part gives way first is how you optimise the wrong thing. These
are measurements, not estimates.

## Measurements

| Quantity | Measured |
|---|---|
| Marginal cost per schedule run | **1.19 s** |
| Pool spawn + shutdown (size 2) | 0.027 s |
| One pool round trip | 0.053 s |
| `evaluate()` — one verdict | **101 ms, 8 DB connections** |
| 20 replays × 4 schedules + 20 (P2) = 100 runs | 148 s |

Method: `test_p2_produces_a_violation` alone (7.17 s, dominated by session
fixture startup) against the full `test_p2.py` (13.11 s, six tests sharing one
fixture). The delta over five additional runs isolates marginal cost.

## Findings

**The pool is not the bottleneck.** 0.027 s of a 1.19 s run — about 2%. The
earlier concern that fork-per-run would dominate was correct in principle and
wrong about magnitude at this scale; pooling still matters, but for correctness
(no leaked state between cases) more than for speed.

**The oracle is the expensive part.** Each verdict opens **8 short-lived
Postgres connections**: three totals × two services, plus the idempotency-key
grouping. `capture_views()` opens more. At 100 ms per verdict this is ~8% of a
run today, and it does not scale:

| Volume | Runs | Verdict connections | Verdict time |
|---|---|---|---|
| Mode A, 15 schedules × 20 replays | 300 | 2,400 | ~30 s |
| 2×2 with LLM arms | 480 | 3,840 | ~48 s |
| **Naturalistic, 10,000 runs** | 10,000 | **80,000** | **~17 min** |

Total projected wall clock at current cost: Mode A ~0.1 h, LLM 2×2 ~0.16 h,
**naturalistic mode ~3.3 h**. The last is the one that hurts, and Postgres's
default `max_connections` of 100 becomes a real ceiling under any concurrency.

## Decision

Change nothing now. All three figures are comfortable at Stage 0 volumes, and
optimising ahead of the measurement that justifies it would add moving parts to
a rig whose entire value is trustworthiness.

**When naturalistic mode arrives, fix in this order:**

1. **Pool the oracle's connections.** Eight per verdict becomes one. Largest win,
   smallest change, no effect on what is measured — the oracle stays read-only
   and still evaluates only at quiescence.
2. **Hoist the agent pool above the run loop.** Currently constructed per
   schedule run. Worth ~2% now, more when runs are thousands.
3. **Batch the totals into one query per service.** Three round trips collapse
   to one; the three state-filters differ only in their `state = ANY(...)`.

**Do not** move the oracle to a long-lived connection shared with the services,
or reuse their connection pool. It must remain a separate read-only principal
that cannot perturb what it measures.

## Note on the pool's start method

`AgentPool` uses `spawn`, so any standalone script constructing one must guard
it behind `if __name__ == "__main__":`. `fork` would remove that requirement and
also copy the parent's memory — including anything a previous case left behind,
which is exactly the leak the pool exists to prevent. The guard is the cheaper
cost. Pytest already satisfies it.
