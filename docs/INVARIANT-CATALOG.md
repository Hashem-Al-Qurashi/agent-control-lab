# Invariant Catalog

The artifact that turns "be careful with agents" into something a machine can
check. Every invariant here is expressed so it can be evaluated over final state
and either holds or does not.

**The hard part is not writing the check.** It is deciding which operations count
toward which limit, where their state lives, and who resolves the ambiguity. No
tool answers that; it comes from the business. Everything below is the *output*
of that conversation, not a substitute for it.

## The taxonomy that matters

The distinction that decides how an invariant can be enforced:

| Kind | Scope | Enforceable by | Example here |
|---|---|---|---|
| **Local** | One row, one database | A `CHECK` constraint or a transaction | `refund.amount > 0` |
| **Cross-service** | Spans systems with no shared transaction | An authority both must consult | `sum(refunds) + sum(credits) ≤ authorized` |
| **Eventual** | True only after propagation settles | A reconciler with a stated window | projection total = sum of applied events |
| **Hard** | One breach is a breach | Deny, never score | `actor.tenant == resource.tenant` |
| **Bounded-time** | Must hold within N of an event | A reaper or timer | a hold expires if unused |

**Getting the kind wrong is how enforcement fails.** A cross-service invariant
given to a `CHECK` constraint cannot see half its inputs. A hard invariant
reported as a percentage tells you 97% of tenant isolation held, which is not a
number that means anything.

---

## Financial

### F1 — Compensation ceiling *(cross-service)*
```
sum(refunds WHERE state IN (COMMITTED, SETTLED))
  + sum(credits WHERE state IN (COMMITTED, SETTLED))
  ≤ authorized_compensation
```
The invariant this repo exists to test. Spans Billing and Ledger; no single
database can evaluate it. VOIDED excluded — a voided row is not an economic
effect.

**Breached by:** `P2`, `S1`, `S3`. **Held by:** `P0`, `S1H` via a reservation
authority.

### F2 — Single-action authority *(local, per action)*
```
action.amount ≤ threshold  OR  actor holds approval scope
```
Deliberately *not* aware of F1. Per-action authorization is not aggregate
correctness, and a policy enforcing both would make every finding circular. A
test asserts the policy module's logic never references the aggregate.

**Held by:** `S6`.

### F3 — One decision, one effect *(local)*
```
count(effects sharing an idempotency_key AND in a committed state) ≤ 1
```
When violated the oracle returns `INCONCLUSIVE`, never `VIOLATION` — two effects
from one decision is a rig defect, and reporting it as a breach would be the
most damaging false positive available because it has the exact shape of the
real result.

---

## Projection

### P1 — Projection consistency *(eventual)*
```
projection.total = sum(applied_events.amount)
AND projection.events_applied = count(applied_events)
```
Checked by the reconciler as `PROJECTION_DRIFT`. A projection disagreeing with
the events it claims to have folded in is corruption, not lag.

### P2 — Bounded lag *(bounded-time)*
```
count(outbox WHERE applied_at IS NULL) = 0   within the reconciliation window
```
**The window is the whole invariant.** "Eventually consistent" without a stated
bound is not a property, it is a hope. Reported as `PROJECTION_LAG`.

### P3 — Redelivery absorption *(eventual)*
```
applied_events is keyed by (source_service, source_id)
```
Event ids are unique only *within* a service, so keying on the id alone silently
drops one of two concurrent events. **Held by:** `S5`.

---

## Authorization

### A1 — Tenant isolation *(hard)*
```
actor.tenant == resource.tenant
```
Deny, never score. One cross-tenant action is a breach; "99.9% of actions stayed
in-tenant" describes a system that leaked data.

### A2 — Identity is not self-asserted *(hard)*
```
every mutating request carries a signature verifiable against a key the actor
does not hold
```
An invalid token is rejected, never degraded to an anonymous identity — a caller
that silently becomes "someone" is how authorization gets bypassed unnoticed.

---

## Reservation lifecycle

### R1 — No hold outlives its action *(bounded-time)*
```
reservation.state = HELD  ⇒  its effect is still in flight
```
A leaked hold occupies budget nothing spent and refuses legitimate later
actions — and that refusal **looks exactly like the control working correctly**,
so nobody investigates. Enforced by release-on-failure.

### R2 — Committed holds are irreversible *(hard)*
```
state = COMMITTED  ⇒  cannot transition to RELEASED
state = RELEASED   ⇒  cannot transition to COMMITTED
```
Releasing a committed hold frees budget genuinely spent. Committing a released
one creates authority out of nothing.

---

## How to derive these for a real system

The catalog is the deliverable; the derivation is the work.

1. **Find the operations that move money or change entitlement.** Not the ones
   that look important — the ones with external effects.
2. **For each, ask what must never be true afterwards.** Phrase it as a
   prohibition; prohibitions are checkable in a way aspirations are not.
3. **Locate every input.** If they span services, it is cross-service and no
   database constraint will reach it.
4. **Decide hard vs scored.** If one breach is unacceptable, it is hard, and it
   must deny rather than appear in a percentage.
5. **For eventual invariants, state the window.** Without a bound there is no
   invariant.
6. **Name who resolves ambiguity.** Every real catalog hits a rule two teams
   state differently. That is a business decision, not an engineering one, and
   pretending otherwise is how a catalog quietly encodes one team's assumption.
