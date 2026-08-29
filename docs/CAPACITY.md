# Capacity

Measured, not estimated. Every number below comes from
`tests/integration/test_capacity.py`, which asserts the correctness property as
it takes the timings.

## What was tested

The question worth asking is not throughput. Every other test in this repo drives
a **scripted** interleaving, which is what makes a violation attributable. That
leaves one thing open: the schedules exercise two or three actors in an order we
chose. Does the reservation authority hold when many agents contend for it at
once, in an order nobody chose?

Setup: a $1,000 ceiling, agents each requesting $100. **Exactly ten can be
granted.** Every request is individually valid; the authority must admit ten and
refuse the rest.

## Results

| Concurrent agents | Granted | Total | p50 | p95 | p99 | max |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | **10** | $1,000.00 | 381 ms | 439 ms | 439 ms | 442 ms |
| 50 | **10** | $1,000.00 | 1,654 ms | 1,810 ms | 1,831 ms | 1,860 ms |
| 100 | **10** | $1,000.00 | 3,262 ms | 3,516 ms | 3,587 ms | 3,638 ms |

**Correctness held exactly at every level.** Not "approximately ten", not
"$1,000.02". Ten grants, one thousand dollars, at 10× the contention the
schedules ever produce.

That matters because P0 and S1H both depend on this primitive. If the authority
admitted an eleventh grant under load, both of those results would be worthless —
they would be showing that a control works in conditions where it happens to
work.

Losers receive a clean `409`, never a `500`. A refusal that surfaces as a server
error is indistinguishable from an outage, and an agent cannot tell *"you may
not"* from *"try again later."*

## Latency scales linearly, and that is the design

p50 goes 381 → 1,654 → 3,262 ms as concurrency goes 10 → 50 → 100. Roughly
linear, and it should be.

Reservations for a case are serialised by a transaction-scoped advisory lock. The
check and the insert **must** be one atomic step, or the control service contains
the very read-check-write race it exists to prevent — which would be an ironic
and entirely silent defect. Serialisation is not an implementation shortcut; it
is the mechanism.

So the control service is a serialisation point **per case**, and throughput for
a single case is bounded by lock hold time. Two consequences:

- **Contention is per-case, not global.** Different cases do not block each
  other, because the lock is keyed on `case_id`. A hundred agents on a hundred
  different invoices do not queue behind one another. A hundred agents on *one*
  invoice do.
- **A hundred concurrent agents on one invoice is not a realistic shape.** It was
  chosen to stress the correctness property, not to model production.

## What this does not measure

Stated so the numbers are not read as more than they are:

- **One machine, five local Postgres containers, no network latency.** Real
  deployments add round trips this does not have.
- **The oracle is excluded.** ADR-003 measured it separately at 8 connections and
  ~101 ms per verdict, and identified it as the first thing to fix at volume. It
  is not in this path.
- **No LLM.** Token cost and model latency are absent by design — the diligent
  agent is deterministic so failures cannot be blamed on a model.
- **Reservation only.** This measures the coordination authority, not the full
  agent path through Billing, Ledger and CRM.

## If contention on a single case ever becomes real

In rough order of what to try:

1. **Shorten the lock.** The transaction currently spans a `SELECT` and an
   `INSERT`. The sum could be maintained incrementally so the held section is a
   single statement.
2. **Reject early, outside the lock.** A request that cannot possibly fit —
   larger than the whole ceiling — needs no lock at all.
3. **Partition the budget.** Sub-ledgers per actor class, reconciled centrally.
   This trades exactness for throughput and should be a last resort: the property
   being protected is that the total is *exactly* right.
