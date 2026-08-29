# ADR-010 — A transactional outbox instead of Kafka

**Status:** accepted · **Date:** 2026-08-29

## Context

`LAB-BUILD.md` lists Kafka for Stage 1, for a real reason: eventual consistency
is part of the thesis, and manufactured propagation delay is not credible.

## The conflict Kafka creates

Determinism is the foundation of every Mode A result. A violation that appears
only sometimes proves nothing, because it cannot be told from scheduling luck.

Kafka fights that. To replay a schedule deterministically you must control
consumer poll timing, partition assignment and offset commits from the
coordinator — controlling a message broker's internals in order to test something
that is not the broker.

## Decision

Use a transactional outbox with an HTTP-exposed event feed. Kafka is not
required for what is being measured.

**What the thesis actually needs is propagation lag that is real rather than
simulated.** The outbox provides exactly that: events are written in the same
transaction as the effect they describe, and a separate consumer applies them
later. The lag is a genuine consequence of asynchronous application, not a
`sleep`.

`LAB-SPEC.md` already sanctioned this: *"v1 uses a simpler controllable event
mechanism; Kafka lands in Stage 5 once schedules are stable."*

## What is lost, honestly

- **Broker semantics**: partition ordering, consumer group rebalancing, replication.
- **Redelivery under real conditions.** `S5` exercises redelivery through an
  explicit endpoint, which is deterministic and therefore *weaker evidence* than
  a broker that duplicated on its own.
- **Realism for a reader who expects Kafka** in a diagram like this one.

## What would change this

Any measurement whose answer depends on broker behaviour: rebalance during a
run, partition-ordering effects on the projection, or a redelivery rate observed
rather than induced.

None of the current findings depend on any of those. The determinism boundary in
`LAB-SPEC.md` was written to make the swap possible later without invalidating
earlier results — the schedule controls *when an event is applied*, not how it
was transported.
