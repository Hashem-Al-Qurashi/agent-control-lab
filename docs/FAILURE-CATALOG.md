# Failure Catalogue

<!-- GENERATED from catalog/failures.yaml by `make catalog`. Do not hand-edit. -->

Named failure modes for action-taking agents. Every entry marked **Reproduced
here** runs on your machine with one command, and a test asserts that claim —
`tests/unit/test_failure_catalog.py` fails if any entry cites a test or schedule
that does not exist.

Status means what it says:

| Status | Meaning |
|---|---|
| **Reproduced here** | A test in this repo produces it on demand |
| Documented in the wild | Observed elsewhere, cited to a primary source read directly |
| Described, not yet reproduced | Named and understood, not demonstrated here |

The third row is why this is usable. A catalogue that admits what it has not
tested is worth more than one that does not distinguish.

## Coverage

**17 entries.**

| Status | Count |
|---|---:|
| **Reproduced here** | 17 |

| Invariant class | Count |
|---|---:|
| `local` | 1 |
| `cross-service` | 5 |
| `eventual` | 4 |
| `hard` | 5 |
| `bounded-time` | 2 |

## Index

| ID | Failure | Class | Status |
|---|---|---|---|
| [`ACL-F01`](#acl-f01) | Read-check-write race across services | `cross-service` | **Reproduced here** |
| [`ACL-F02`](#acl-f02) | Stale read model with no concurrency at all | `cross-service` | **Reproduced here** |
| [`ACL-F03`](#acl-f03) | A fresher view narrows the window without closing it | `eventual` | **Reproduced here** |
| [`ACL-F04`](#acl-f04) | Ambiguous outcome after a lost acknowledgement | `local` | **Reproduced here** |
| [`ACL-F05`](#acl-f05) | Redelivered event inflates a projection | `eventual` | **Reproduced here** |
| [`ACL-F06`](#acl-f06) | Events applied out of order | `eventual` | **Reproduced here** |
| [`ACL-F07`](#acl-f07) | Action crosses a tenant boundary | `hard` | **Reproduced here** |
| [`ACL-F08`](#acl-f08) | A scope reused for an action it does not authorize | `hard` | **Reproduced here** |
| [`ACL-F09`](#acl-f09) | Forged, tampered or self-asserted identity | `hard` | **Reproduced here** |
| [`ACL-F10`](#acl-f10) | A credential outliving its authority | `hard` | **Reproduced here** |
| [`ACL-F11`](#acl-f11) | Entitlement stranded by a plan change | `cross-service` | **Reproduced here** |
| [`ACL-F12`](#acl-f12) | Aggregate exactness under contention | `cross-service` | **Reproduced here** |
| [`ACL-F13`](#acl-f13) | A model-driven agent breaches identically | `cross-service` | **Reproduced here** |
| [`ACL-F14`](#acl-f14) | A breach invisible to every health signal | `eventual` | **Reproduced here** |
| [`ACL-F15`](#acl-f15) | An approval outliving the decision it was granted for | `bounded-time` | **Reproduced here** |
| [`ACL-F16`](#acl-f16) | An abandoned hold refuses an action the ceiling permits | `bounded-time` | **Reproduced here** |
| [`ACL-F17`](#acl-f17) | An unbound approval acting as a master key | `hard` | **Reproduced here** |

---

## ACL-F01

### Read-check-write race across services

**Family:** `concurrency` · **Invariant class:** `cross-service` · **Status:** **Reproduced here**

**Symptom.** Two individually-valid actions combine past an aggregate ceiling. Each agent's decision is correct; the total is not.

**Mechanism.** Both agents read before either writes. The ceiling spans two services with separate databases, so no transaction and no constraint can see the sum that is being violated.

**What monitoring shows.** Both agents report success. Every span is OK. The reconciler finds no drift.

**Control.** An authority that can see every input to the invariant at decision time, consulted before the action rather than validating after it.

**Reproduce:**

```
make reproduce SCHEDULE=P2
```

**Verified by:** `test_p2_produces_a_violation`, `test_p2_overage_is_exactly_one_hundred`

**Control verified by:** `test_p0_does_not_violate_under_p2s_interleaving`, `test_p0_and_p2_differ_only_in_the_available_interface`

**Schedules:** `P2`

---

## ACL-F02

### Stale read model with no concurrency at all

**Family:** `stale-state` · **Invariant class:** `cross-service` · **Status:** **Reproduced here**

**Symptom.** An agent acting strictly after another has finished still produces an invalid aggregate.

**Mechanism.** The second agent reads a projection that has not yet applied the first agent's event. Its observation is wrong the instant the first commit lands, and nothing tells it so.

**What monitoring shows.** Identical to a healthy run. This is the entry that ends the "just stop them overlapping" conversation.

**Control.** An authority holding authoritative state rather than a derived view, so staleness stops being able to cause harm.

**Reproduce:**

```
make reproduce SCHEDULE=S1
```

**Verified by:** `test_s1_violates_even_though_the_actors_never_overlap`, `test_s1_is_strictly_sequential`, `test_s1_violates_while_every_action_was_authorized`

**Control verified by:** `test_s1h_is_clean`, `test_s1h_projection_was_just_as_stale_as_in_s1`

**Schedules:** `S1`

**Note.** The flagship entry. S1C is the negative control: the same schedule with the projection caught up returns CLEAN, isolating staleness as the variable.

---

## ACL-F03

### A fresher view narrows the window without closing it

**Family:** `stale-state` · **Invariant class:** `eventual` · **Status:** **Reproduced here**

**Symptom.** Partially catching the projection up reduces exposure and still permits the breach.

**Mechanism.** The window stays open until a write lands somewhere else. No read closes a window whose duration is owned by another system.

**What monitoring shows.** Clean. Projection lag is smaller than in ACL-F02, which reads as an improvement.

**Control.** Same as ACL-F02 — freshness is not the lever.

**Reproduce:**

```
make reproduce SCHEDULE=S3
```

**Verified by:** `test_s3_violates_despite_partial_catch_up`, `test_s3_third_actor_saw_a_partially_current_view`

**Control verified by:** `test_s1h_is_clean`

**Schedules:** `S3`

**Note.** The answer to "then make the projection faster". Exposure tracks lag; it does not vanish with it.

---

## ACL-F04

### Ambiguous outcome after a lost acknowledgement

**Family:** `ambiguous-execution` · **Invariant class:** `local` · **Status:** **Reproduced here**

**Symptom.** The effect is durable but the caller never learns it, so a retry risks a second economic effect.

**Mechanism.** The write commits and the acknowledgement is lost in transit. Success and failure are indistinguishable from outside the boundary.

**What monitoring shows.** A retry, which looks like ordinary transient-failure handling.

**Control.** An idempotency key enforced by a uniqueness constraint, plus no application-level retry loop.

**Reproduce:**

```
make reproduce SCHEDULE=P3
```

**Verified by:** `test_p3_creates_exactly_one_refund_despite_the_retry`, `test_p3_commits_once_even_though_the_create_path_ran_twice`

**Control verified by:** `test_p3_is_clean`, `test_p3_is_not_reported_as_inconclusive`

**Schedules:** `P3`

**Note.** Included because it PASSES. Idempotency stops one operation applying twice; it is orthogonal to two different valid operations summing past a ceiling, and conflating them is the most common misdiagnosis of ACL-F01.

---

## ACL-F05

### Redelivered event inflates a projection

**Family:** `messaging` · **Invariant class:** `eventual` · **Status:** **Reproduced here**

**Symptom.** An at-least-once event applied twice makes a derived view report more than was ever committed.

**Mechanism.** The projector applies an event it has already absorbed, because nothing records which source events are spent.

**What monitoring shows.** Nothing. The projection is internally consistent; it is simply wrong.

**Control.** Applied-event bookkeeping keyed on (source service, source id), committed with the projection it advances.

**Reproduce:**

```
make reproduce SCHEDULE=S5
```

**Verified by:** `test_s5_redelivery_does_not_move_the_projection`, `test_s5_stays_clean`

**Control verified by:** `test_applied_events_are_not_reclaimed`, `test_source_is_marked_applied_only_after_the_projection_commits`

**Schedules:** `S5`

**Note.** Dangerous because it fabricates a violation with the exact shape of a real one — the most damaging false positive available to this harness.

---

## ACL-F06

### Events applied out of order

**Family:** `messaging` · **Invariant class:** `eventual` · **Status:** **Reproduced here**

**Symptom.** Two events arriving in either order must converge on the same state, and a projection that assumes order silently will not.

**Mechanism.** Independent producers give no cross-service ordering guarantee.

**What monitoring shows.** Nothing.

**Control.** Commutative application — sums rather than sequence-dependent updates.

**Reproduce:**

```
make reproduce SCHEDULE=S4
```

**Verified by:** `test_s4_reversed_apply_order_reaches_the_same_state`, `test_s4_b_declined_because_it_saw_the_correct_total`

**Control verified by:** `test_reversed_order_produces_the_same_total`

**Schedules:** `S4`

**Note.** A negative control. It rules ordering out as the cause of ACL-F01, which matters because "your events are out of order" is the second-most-common wrong explanation.

---

## ACL-F07

### Action crosses a tenant boundary

**Family:** `authorization` · **Invariant class:** `hard` · **Status:** **Reproduced here**

**Symptom.** An actor acts on a resource belonging to another customer.

**Mechanism.** Tenant is treated as an attribute to be scored rather than a boundary to be denied.

**What monitoring shows.** A 403, which looks like the system working.

**Control.** A hard deny on tenant mismatch, never a weighted decision.

**Reproduce:**

```
pytest tests/integration/test_abuse.py -q
```

**Verified by:** `test_a_cross_tenant_action_is_rejected`, `test_cross_tenant_action_is_always_denied`

**Control verified by:** `test_a_token_for_another_tenant_cannot_act_on_this_one`

**Note.** One breach is a breach. This class must never be reported as a percentage.

---

## ACL-F08

### A scope reused for an action it does not authorize

**Family:** `authorization` · **Invariant class:** `hard` · **Status:** **Reproduced here**

**Symptom.** An agent holding authority for one action performs a different one.

**Mechanism.** Authorization checks that a caller is authenticated and has *some* scope, rather than the scope for this action.

**What monitoring shows.** Nothing — the call is authenticated and succeeds.

**Control.** Per-action scope evaluated by the service, never by the agent.

**Reproduce:**

```
pytest tests/integration/test_abuse.py -q
```

**Verified by:** `test_scope_for_one_action_does_not_authorize_another`, `test_a_missing_scope_is_rejected`

**Control verified by:** `test_the_policy_is_deterministic`

---

## ACL-F09

### Forged, tampered or self-asserted identity

**Family:** `authorization` · **Invariant class:** `hard` · **Status:** **Reproduced here**

**Symptom.** An agent widens its own authority, making every downstream authorization decision meaningless.

**Mechanism.** Identity taken from a header the caller controls, or a token whose signature is not verified against a key the caller does not hold.

**What monitoring shows.** Nothing, if the forgery succeeds — the actions look like a legitimate actor.

**Control.** Signed, externally-issued identity; invalid credentials rejected outright rather than degraded to anonymous.

**Reproduce:**

```
pytest tests/unit/test_identity_policy.py tests/integration/test_abuse.py -q
```

**Verified by:** `test_a_tampered_token_is_rejected`, `test_a_token_signed_with_another_key_is_rejected`, `test_the_actor_header_cannot_override_the_token_subject`

**Control verified by:** `test_an_unsigned_token_shaped_string_is_refused`, `test_a_missing_token_is_rejected`

---

## ACL-F10

### A credential outliving its authority

**Family:** `authorization` · **Invariant class:** `hard` · **Status:** **Reproduced here**

**Symptom.** A leaked or stale token keeps working indefinitely, so revocation has no effect.

**Mechanism.** Tokens minted without an expiry, or an expiry verified only when present — a check that passes by not applying.

**What monitoring shows.** Nothing. The calls are valid.

**Control.** Lifetime enforced at the service boundary, and a credential without an expiry refused rather than trusted.

**Reproduce:**

```
pytest tests/unit/test_identity_policy.py -q
```

**Verified by:** `test_an_expired_token_is_refused_at_the_service_boundary`, `test_a_token_without_an_expiry_is_rejected`

**Control verified by:** `test_an_expired_token_is_a_401_not_a_500`

**Note.** Replay INSIDE the validity window remains possible here — there is no jti ledger. Stated as T1's residual rather than implied away.

---

## ACL-F11

### Entitlement stranded by a plan change

**Family:** `stale-state` · **Invariant class:** `cross-service` · **Status:** **Reproduced here**

**Symptom.** A customer keeps a feature their current plan does not permit, with no money involved anywhere.

**Mechanism.** Grants live in one service and the plan in another. The aggregate rule "granted features are a subset of permitted features" has no owner.

**What monitoring shows.** Nothing. Both services are internally consistent.

**Control.** An authority owning the subset relation across both services.

**Reproduce:**

```
pytest tests/integration/test_entitlement_workflow.py -q
```

**Verified by:** `test_a_downgrade_strands_a_grant_the_new_plan_forbids`, `test_a_grant_outside_the_plan_is_a_violation`

**Control verified by:** `test_a_grant_within_the_plan_is_clean`

**Note.** The same structure as ACL-F01 with no arithmetic in it, so the finding cannot be dismissed as an accounting problem.

---

## ACL-F12

### Aggregate exactness under contention

**Family:** `concurrency` · **Invariant class:** `cross-service` · **Status:** **Reproduced here**

**Symptom.** Under load a budget authority admits approximately the right number of actions instead of exactly the right number.

**Mechanism.** The check and the grant are not one atomic step, so the authority contains the very read-check-write race it exists to prevent.

**What monitoring shows.** Rising latency, which reads as load rather than as a correctness risk.

**Control.** Check and grant inside one transaction-scoped lock, keyed per case so contention stays local.

**Reproduce:**

```
pytest tests/integration/test_capacity.py -q
```

**Verified by:** `test_the_ceiling_holds_under_contention`, `test_refusals_are_refusals_not_errors`

**Control verified by:** `test_the_ceiling_holds_under_contention`

**Note.** Measured at 10, 50 and 100 concurrent agents: exactly ten grants and exactly $1,000.00 every time. Losers receive 409, never 500.

---

## ACL-F13

### A model-driven agent breaches identically

**Family:** `concurrency` · **Invariant class:** `cross-service` · **Status:** **Reproduced here**

**Symptom.** Replacing the deterministic agent with a real LLM changes nothing about the outcome.

**Mechanism.** The model reads before acting — diligently — and its read and its write are still not atomic across services. Cognition was never the problem.

**What monitoring shows.** Nothing. The agent's reasoning is sound and its calls succeed.

**Control.** The same coordination authority. It holds with cognition in the loop, unchanged.

**Reproduce:**

```
make test-llm
```

**Verified by:** `test_arm_c_reproduces_the_violation_with_a_real_model`, `test_arm_c_agents_read_before_acting`

**Control verified by:** `test_arm_d_never_breaches_the_ceiling`, `test_arm_d_refusals_come_from_the_control_not_the_harness`

**Note.** Five of five runs breached at $1,100 without the authority; five of five stayed clean with it. Requires DEEPSEEK_API_KEY.

---

## ACL-F14

### A breach invisible to every health signal

**Family:** `reconciliation` · **Invariant class:** `eventual` · **Status:** **Reproduced here**

**Symptom.** Task success, distributed tracing and reconciliation all report healthy while the business state is wrong.

**Mechanism.** Each signal answers a question correctly, and none of them is asked whether the business state is right. Operational health and business correctness are different measurements.

**What monitoring shows.** Three green signals agreeing. Their agreement is the finding.

**Control.** An invariant checker that reads across service boundaries, run separately from operational monitoring.

**Reproduce:**

```
make reproduce SCHEDULE=S1
```

**Verified by:** `test_ordinary_monitoring_does_not_see_the_s1_breach`, `test_a_fully_caught_up_breach_produces_no_findings_at_all`, `test_every_span_in_the_breaching_run_reports_success`

**Control verified by:** `test_violation_when_the_sum_exceeds_the_ceiling`, `test_calibration_passes_with_the_real_oracle`

**Schedules:** `S1`, `S3`

**Note.** The reason "add more observability" does not address this class. Measured, not asserted — the reconciler is genuinely clean during the breach.

---

## ACL-F15

### An approval outliving the decision it was granted for

**Family:** `approval` · **Invariant class:** `bounded-time` · **Status:** **Reproduced here**

**Symptom.** An agent acts on authority a human granted much earlier, for a decision that has since moved on.

**Mechanism.** Approval is carried as a session scope, so it lives as long as the token. A human approving one action is not approving whatever that agent does for the rest of the hour, but nothing in the check distinguishes those.

**What monitoring shows.** An authorised action by an authenticated actor. Nothing to alert on.

**Control.** A grant carrying its own validity window, revalidated at execution rather than only at decision, and refused outright when it carries no window.

**Reproduce:**

```
pytest tests/integration/test_approval_expiry.py tests/unit/test_approvals.py -q
```

**Verified by:** `test_a_scope_approval_never_expires_within_the_session`, `test_a_grant_past_its_window_is_refused`

**Control verified by:** `test_the_same_grant_is_refused_once_its_window_closes`, `test_a_grant_without_a_window_is_refused_rather_than_trusted_forever`

**Note.** Refusing a grant with no deadline is the load-bearing half. Treating "no expiry" as "never expires" is the same defect as verifying a token's exp only when present -- a check that passes by not applying.

---

## ACL-F16

### An abandoned hold refuses an action the ceiling permits

**Family:** `crash-recovery` · **Invariant class:** `bounded-time` · **Status:** **Reproduced here**

**Symptom.** A legitimate action is refused by budget that is occupied by nothing, because an agent reserved and never came back.

**Mechanism.** Holds had no deadline, so a hold survived the agent that took it. Nothing was ever committed, so the true aggregate permitted the later action.

**What monitoring shows.** A 409 from the coordination authority -- exactly what a legitimate refusal looks like. That indistinguishability is why nobody investigates.

**Control.** Deadlines on holds, reclaimed inside the reservation lock so a dead agent's budget is already free when a live agent contends for it.

**Reproduce:**

```
make reproduce SCHEDULE=S8
```

**Verified by:** `test_s8_refused_an_action_the_ceiling_permitted`, `test_s8_leaves_a_hold_that_nothing_will_release`, `test_the_refusal_is_indistinguishable_from_a_correct_one`

**Control verified by:** `test_expiry_is_what_makes_the_budget_recoverable`, `test_a_live_agent_succeeds_once_the_dead_agents_hold_has_lapsed`, `test_a_committed_hold_is_never_reaped`

**Schedules:** `S8`

**Note.** The failure with the opposite sign. Everywhere else here money moves when it should not; this is money not moving when it should -- and the oracle returns CLEAN, because it asks whether too much was spent. Too little is invisible to it, which is why this needs its own detection rather than a stricter version of the existing one.

---

## ACL-F17

### An unbound approval acting as a master key

**Family:** `approval` · **Invariant class:** `hard` · **Status:** **Reproduced here**

**Symptom.** One approval authorises actions it was never meant to cover -- a different case, a different action, or a larger amount.

**Mechanism.** The check confirms that an approval exists rather than that this approval covers this action.

**What monitoring shows.** An approved action. The approval is real; it simply belonged to something else.

**Control.** Grants bound to one case, one action and one ceiling.

**Reproduce:**

```
pytest tests/unit/test_approvals.py -q
```

**Verified by:** `test_a_grant_for_another_case_does_not_transfer`, `test_a_grant_for_another_action_does_not_transfer`, `test_a_grant_does_not_authorise_more_than_it_approved`

**Control verified by:** `test_a_grant_authorises_less_than_it_approved`

**Note.** Approving $600 is not approving $900, and approving case c1 is not approving c2. Without binding, the first approval a system ever issues authorises every action after it.
