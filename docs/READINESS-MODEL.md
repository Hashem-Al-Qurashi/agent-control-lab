# Production Agent Readiness Model

Ten domains. Each has a question that can be answered with evidence rather than
opinion, and a failure mode that this lab either demonstrated or explicitly did
not test.

**What makes this different from a generic checklist:** every domain cites what
was actually measured here, including the domains where the answer was "this
holds and it still wasn't enough." A model that only lists good practices cannot
explain why a system doing all of them still ends up wrong.

Score each domain **Absent · Partial · Held**. The scoring is less important than
the evidence column — a "Held" with no evidence is an opinion.

---

## 1. Agent behaviour

**Question:** Can you tell a bad decision from a bad outcome?

Task success and business correctness are different measurements. In `S1` every
agent succeeded at its task and the business state was wrong.

| Check | Evidence to demand |
|---|---|
| Task success measured separately from business correctness | two distinct numbers, not one |
| Decisions reproducible given the same observations | replay produces the same decision |
| The agent's *observable state* is recorded, not just its output | you can ask "what did it see?" |

**Failure mode demonstrated:** an agent that is correct given everything it could
observe, and wrong anyway.

## 2. Tool execution

**Question:** What happens when a tool call's outcome is unknown?

| Check | Evidence |
|---|---|
| Every mutating call carries an idempotency key | `P3`: one effect from two attempts |
| Retries are explicit keyed decisions, never automatic | ADR-001 |
| Ambiguous outcomes have a defined resolution | lost-ACK path is tested, not assumed |
| No proxy or mesh retries on your behalf | **untested here** — a real gap, T5 |

## 3. Identity

**Question:** Could the agent widen its own authority?

| Check | Evidence |
|---|---|
| Identity is signed, externally issued, unforgeable | tampered and wrong-key tokens rejected |
| Invalid credentials are rejected, never degraded to anonymous | a caller that silently becomes "someone" is how authz gets bypassed |
| Tokens expire | `test_an_expired_token_is_refused_at_the_service_boundary` — enforced at the boundary, not only in the library |
| A credential minted without an expiry is refused | fail closed: verifying `exp` only when present accepts an immortal token forever |
| Keys rotate; replay inside the window is stopped | **absent here** — ADR-005, T1 |

## 4. Authorization

**Question:** Who decides, and can the agent influence it?

| Check | Evidence |
|---|---|
| Policy evaluated outside the agent | the agent has no code path to it |
| Decisions deterministic | same inputs, same outcome, 50× |
| Hard invariants deny rather than score | tenant isolation is a deny, not a percentage |
| **Per-action authorization is not confused with aggregate correctness** | `S6` holds; `S1` breaches anyway |

**This is the domain most often marked Held incorrectly.** Working authorization
and a correct aggregate are different properties, and `S6` vs `S1` is the
demonstration.

## 5. Business correctness

**Question:** Is there an authority for each invariant, at the right scope?

| Check | Evidence |
|---|---|
| Invariants written down and classified | local / cross-service / eventual / hard / bounded-time |
| Each has an authority that can *see all its inputs* | `P0`, `S1H` |
| Cross-service invariants are not delegated to a database constraint | a `CHECK` cannot see another database |
| Someone owns ambiguity between teams | not a technical decision |

**The domain this lab exists for.** Absent here is the default state, and it is
invisible from inside any single service.

## 6. Reliability

**Question:** Does a partial failure leave partial state?

| Check | Evidence |
|---|---|
| Effect and its event commit atomically | structural lint, not a behavioural test |
| Denied actions leave nothing behind | authorization precedes the transaction |
| Holds are released when their action fails | `test_a_failed_action_releases_its_hold` |
| A hold survives its agent dying | **absent** — T9, trigger 2 in ADR-006 |

## 7. Observability

**Question:** Would you find out?

| Check | Evidence |
|---|---|
| One trace spans the decision and every call it caused | traceparent travels with identity |
| Real failures are recorded as failures | mutation-verified |
| Reconciliation checks operational health | lag, drift, duplicates, orphans |
| **Business invariants checked separately from operational health** | `S1`, `S3`: reconciler clean, money wrong |

**The distinction in the last row is the point.** Operational monitoring and
invariant checking answer different questions. A system with excellent
observability and no invariant checker will not detect this class of breach —
measured, not asserted.

## 8. Security

**Question:** What does a rejected request leave behind?

| Check | Evidence |
|---|---|
| Rejections are 4xx with a reason, not 5xx | an abuse attempt must not look like an outage |
| Input validated at the boundary, not only at the database | found as a real defect here |
| Escalation paths tested — horizontal and vertical | scope-for-one-action, cross-tenant |
| Authority comes from the signature, not a header | pinned by test |

## 9. Operations

**Question:** Can someone act on this at 3am without you?

| Check | Evidence |
|---|---|
| Runbook per alert that can fire | `docs/RUNBOOKS.md` |
| SLOs distinguish "slow" from "wrong" | `docs/SLOS.md` |
| Prohibited outcomes are counted, never averaged | zero cross-tenant, not 99.9% |
| A worked incident exists | `docs/INCIDENT-001.md` |

## 10. Cost and scaling

**Question:** Where does it give way, and have you measured or guessed?

| Check | Evidence |
|---|---|
| Bottleneck measured, not assumed | ADR-003: it was the oracle, not the pool — a 50× error in my guess |
| Coordination correctness verified under contention | exactly 10 grants at 100 concurrent |
| Serialisation points identified and scoped | per-case, not global |
| Exposure quantified against a real variable | Mode B: exposure vs arrival separation |

---

## How to use this

1. **Demand evidence per row, not a rating.** "Held" without an artifact is an
   opinion with a checkbox.
2. **Expect domains 1–4 and 6–8 to be strong** in any competent team. They
   usually are. That is not reassurance.
3. **Domain 5 is where the loss lives**, and it is invisible from inside any
   single service, which is why nobody has raised it.
4. **Domain 7 row 4 is the one that decides how you find out** — whether by
   alert, by a customer, or by finance three weeks later.

A system scoring Held on nine domains and Absent on domain 5 is exactly the
system in `RESULTS.md`: well-engineered, properly controlled, thoroughly
monitored, and wrong by $100 with nothing reporting it.
