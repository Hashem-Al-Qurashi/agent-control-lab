# ADR-001 — No application-level retry loops

**Status:** accepted · **Date:** 2026-08-29

## Context

The plan carried a global constraint:

> HTTP client auto-retry is disabled on non-idempotent endpoints — a client retry
> is indistinguishable from two agents racing.

A test was written to enforce it. The test passed with `retries=0` **and** with
`retries=3`, which meant it asserted nothing. That was only discovered by
mutation-checking it; it had been counted as coverage.

## Measurement

`httpx`'s `retries` parameter was measured directly against a real socket:

| Scenario | `retries=5` | Requests reaching the server |
|---|---|---|
| Server responds 500 | not retried | **1** |
| Connection closed after the request was sent | not retried | **1** |

`retries` covers **connection establishment only**. A connect-level retry cannot
duplicate a side effect, because the request never arrived at the server.

## Decision

The constraint's mechanism was wrong. It is restated as:

> **No application-level retry loops.** A retry must be an explicit, keyed
> decision made by the agent.

`transport=httpx.HTTPTransport(retries=0)` stays as defence in depth, but it is
not what protects the experiment.

The real risk lives in our own code: a `for attempt in range(3)` loop in the
lost-ACK case, where the server has already done the work and the response never
arrived. That would create a second economic effect from one logical decision,
and the oracle would report a violation that never happened — a false positive
with the exact shape of the result being claimed.

`tests/integration/test_no_retry.py` now injects that loop as its mutation and
fails with *"3 requests reached the server for one decision."*

P3 exercises the legitimate case: an ambiguous outcome, retried deliberately
with the same idempotency key, producing exactly one effect.

## Consequence

A constraint with a correct conclusion and a wrong justification is worse than
no constraint, because it directs the guard at the wrong mechanism. Every
load-bearing assertion in this repo is now mutation-checked before being
believed.
