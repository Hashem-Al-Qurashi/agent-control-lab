# ADR-013 — What "correct" means here

**Status:** accepted · **Date:** 2026-08-29

Every verdict in `RESULTS.md` depends on this definition. It is stated as an ADR
because choosing it differently changes what the lab finds — and one of the
tempting choices would have designed the fix into the failure.

## The monetary invariant

```
sum(refunds) + sum(credits) ≤ authorized_compensation
```

counting rows in `COMMITTED` or `SETTLED`, excluding `VOIDED`.

- **`SETTLED` counts.** Money that has moved is money spent —
  `test_settled_counts_toward_the_verdict`.
- **`VOIDED` does not.** A reversed action consumed nothing —
  `test_voided_rows_are_excluded_from_the_verdict`.
- **`PENDING` does not count toward the verdict.** This is the load-bearing one.

## Why PENDING is excluded

Counting `PENDING` against the budget would make an in-flight intention consume
authority — which *is* a reservation. Building that into the verdict would design
the fix into the failure, and the rebuttal writes itself: *"then just make PENDING
a reservation."*

The reservation must be a **separate control that a schedule can turn on and off**,
so `P2` versus `P0` and `S1` versus `S1H` isolate its effect. It cannot also be
the definition of the thing being measured.

`PENDING`-inclusive and `SETTLED`-only totals are still emitted, as **secondary
numbers from the same dataset** — never as the verdict. That preserves
comparability without letting the alternative definition decide anything.
`test_totals_are_always_one_of_the_reachable_states` keeps them honest.

## `authorized_compensation` is policy, not a column

It lives in configuration, not in Billing. Making it a Billing column would make
Billing the authority for an aggregate spanning Billing *and* Ledger — a service
enforcing a bound over data it cannot see. That is the confusion the lab exists to
expose, and encoding it in the schema would hide it.

## INCONCLUSIVE is a third verdict, not a failure

Two rows sharing an idempotency key mean **service idempotency broke**. The sum is
over the ceiling, but the cause is a rig defect, not an aggregate breach.

Reporting that as `VIOLATION` would make `P3` pass for the wrong reason and would
let a broken instrument produce the lab's headline result.
`test_same_idempotency_key_twice_is_inconclusive_not_a_violation`,
`test_duplicate_key_is_inconclusive_even_when_under_the_ceiling`.

## The invariant is not about money

`E1` is non-monetary: granted features ⊆ features permitted by the current plan.
Same structure — an aggregate spanning services with no shared transaction — with
no arithmetic anywhere. `test_a_grant_outside_the_plan_is_a_violation`,
`test_a_downgrade_strands_a_grant_the_new_plan_forbids`.

It is in the repo so the finding cannot be dismissed as an accounting problem.

## Correct ≠ successful

The distinction the whole lab turns on. In `S1` every agent succeeded at its task,
every action was authorized, and the business state was wrong:
`test_s1_violates_while_every_action_was_authorized`.

**Task success and business correctness are different measurements, and a system
that reports only the first cannot report this class of failure at all.**
