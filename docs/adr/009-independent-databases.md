# ADR-009 — One database per service, and never a shared one

**Status:** accepted · **Date:** 2026-08-28

## Decision

Each service owns a database no other service can read or write. Five services,
five Postgres instances, differing in both host port and database name.

## Why this is the premise, not a preference

The experiment asks whether an aggregate invariant can be breached by
individually-valid actions. That question **only exists** when no single
transaction can span the inputs.

Put refunds and credits in one database and a `CHECK` constraint or a serialized
transaction resolves the whole thing. There would be nothing to study, and any
"finding" would be an artifact of a schema choice.

## What this forces, deliberately

- **No cross-service joins.** The oracle reads both databases separately and
  cannot rely on a consistent snapshot across them — which is exactly why
  evaluation is gated on quiescence.
- **The outbox is per-service**, because there is nowhere shared to put it.
- **The projector reads over HTTP**, never into another service's database. A
  projector with direct database access would quietly dissolve the boundary this
  ADR exists to hold.
- **The control service needs its own store.** Putting the compensation ceiling
  in Billing would make Billing authoritative for the aggregate and collapse the
  experiment into a weaker single-system one.

## Enforcement

Asserted, not trusted. `test_billing_and_ledger_use_different_hosts_and_database_names`
checks the DSNs differ in host *and* name; a teardown assertion checks the two
never shared a connection string.

**One config typo pointing two services at one database would turn every result
in this repo into an artifact**, and it would do so silently — every test would
still pass, and the violations would simply stop appearing.
