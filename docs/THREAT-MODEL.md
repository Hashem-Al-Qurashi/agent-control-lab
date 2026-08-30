# Threat Model

Scope: the action-taking path. An agent decides, a service authorizes, an effect
is written, an event propagates, a projection updates.

**Every control row cites a test that exists.** A threat model whose controls are
described rather than verified is a list of intentions — it drifts the moment
someone refactors, and nobody notices because prose does not fail.

Residual risk is stated where it is real. A model with no residual risk has not
been thought about.

---

## Trust boundaries

```
agent process ──HTTP──> service ──SQL──> its own database
      │                    │
      │                    └──outbox──> projector ──> projection
      └──HTTP──> coordination authority
```

Four boundaries. The agent trusts nothing it did not receive signed. Each
service trusts only its own database. The projector trusts event ids only within
their originating service. The oracle trusts nothing — it reads databases
directly, read-only, and imports no service code.

---

## Threats

### T1 — Agent forges or widens its own identity
| | |
|---|---|
| **Impact** | Every authorization decision downstream is meaningless |
| **Control** | Signed token verified against a key the agent does not hold |
| **Verified by** | `test_a_tampered_token_is_rejected`, `test_a_token_signed_with_another_key_is_rejected` |
| **Residual** | Lifetime is now enforced — `test_an_expired_token_is_rejected`, `test_a_token_without_an_expiry_is_rejected`, and rejected at the boundary by `test_an_expired_token_is_refused_at_the_service_boundary`. **Replay inside the window is still possible**: there is no `jti` ledger, so a credential leaked and reused before it expires is accepted. Key rotation and discovery remain absent — ADR-005 |

### T2 — Agent decides its own permissions
| | |
|---|---|
| **Impact** | An actor that evaluates its own authority has none |
| **Control** | Policy evaluated by the service; the agent never calls it |
| **Verified by** | `test_a_missing_scope_is_rejected`, `test_the_policy_is_deterministic` |
| **Residual** | None material. The agent has no code path to the policy |

### T3 — Cross-tenant action
| | |
|---|---|
| **Impact** | Data or money crosses a customer boundary. One breach is a breach |
| **Control** | Hard deny on tenant mismatch, never scored |
| **Verified by** | `test_a_cross_tenant_action_is_rejected` |
| **Residual** | Tenant is taken from a header defaulting to the token claim. A service trusting a header over the claim would be exploitable — the claim is authoritative here, but that is a convention worth making structural |

### T4 — A denied action leaves partial state
| | |
|---|---|
| **Impact** | An effect or event exists for an action that was refused |
| **Control** | Authorization runs *before* the transaction opens, not inside it |
| **Verified by** | `test_a_rejected_action_leaves_no_effect_and_no_event` — mutation-verified by moving `authorize()` after the commit |
| **Residual** | None material |

### T5 — Retry produces a second economic effect
| | |
|---|---|
| **Impact** | Money moves twice for one decision |
| **Control** | Idempotency key enforced by a UNIQUE constraint; no application-level retry loop |
| **Verified by** | `P3`, `test_lost_ack_produces_exactly_one_request` — mutation-verified by inserting a retry loop |
| **Residual** | Client-level retry is proven absent; a proxy or service mesh retrying on our behalf is **not** modelled and would defeat this |

### T6 — Event committed without its effect, or vice versa
| | |
|---|---|
| **Impact** | Propagation lag becomes a harness bug rather than a real property; the projection permanently disagrees with truth |
| **Control** | `publish()` takes the caller's cursor, sharing the effect's transaction |
| **Verified by** | `test_publish_shares_the_effects_transaction` — a **structural** lint, because behaviour cannot check this: moving publish outside the transaction passed all nine functional tests |
| **Residual** | None material |

### T7 — Redelivered event double-counts
| | |
|---|---|
| **Impact** | The projection inflates and **fabricates a violation with the exact shape of the real result** — the most damaging false positive available |
| **Control** | `applied_events` keyed by `(source_service, source_id)` |
| **Verified by** | `S5`, `test_redelivery_after_a_successful_apply_does_not_double_count` |
| **Residual** | None material for redelivery. Event *loss* is a separate threat (T8) |

### T8 — Event lost, projection permanently behind
| | |
|---|---|
| **Impact** | An agent reads a view that never becomes correct |
| **Control** | Source marked applied only *after* the projection commits; reconciler reports `PROJECTION_LAG` |
| **Verified by** | `test_source_is_marked_applied_only_after_the_projection_commits`, `test_unapplied_events_are_detected_as_lag` |
| **Residual** | **Real.** The lag window is unbounded — nothing expires or escalates a stuck event. A production system needs an alerting threshold |

### T9 — Reservation leaks and blocks legitimate actions
| | |
|---|---|
| **Impact** | Budget occupied by nothing. Later valid actions refused, and **the refusal looks exactly like the control working**, so nobody investigates |
| **Control** | Release on failure; idempotent; committed holds cannot be released |
| **Verified by** | `test_a_failed_action_releases_its_hold`, `test_releasing_twice_is_idempotent` |
| **Residual** | Holds now carry deadlines and are reclaimed inside the reservation lock — `test_a_live_agent_succeeds_once_the_dead_agents_hold_has_lapsed`, `ACL-F16`. **The fix introduced a new residual:** an agent dying between its effect and its hold-commit leaves money spent while the hold is reclaimed, permitting an over-spend (`ACL-F18`). The control service cannot detect that — it cannot read the effect stores — so this is detected by the reconciler rather than prevented |

### T10 — The oracle perturbs what it measures
| | |
|---|---|
| **Impact** | The judge changes the outcome; verdicts become unfalsifiable |
| **Control** | Read-only role with `INSERT/UPDATE/DELETE` revoked; evaluates only at quiescence |
| **Verified by** | `test_oracle_credentials_cannot_write` — attempts a write, asserts permission denied |
| **Residual** | None material |

### T11 — A bug shared between the system and its judge cancels out
| | |
|---|---|
| **Impact** | The single failure mode a judge must not have — a defect present in both is invisible |
| **Control** | The oracle writes its own SQL and imports no service code |
| **Verified by** | `test_oracle_imports_no_service_code` — an AST check, not a convention |
| **Residual** | The oracle duplicates schema knowledge, so a migration can desynchronise it. Deliberate: divergence is loud, shared-bug cancellation is silent |

### T12 — The harness manufactures its own result
| | |
|---|---|
| **Impact** | Every finding is worthless, and looks identical to a real one |
| **Control** | Oracle calibrated against a planted violation *and* a planted safe state before any schedule; barrier fails closed; negative controls (`P1`, `S1C`, `S4`, `S5`, `S6`) must pass |
| **Verified by** | `oracle/calibration.py`, run in the stack fixture before every schedule |
| **Residual** | Calibration covers three planted cases. A defect outside those shapes would pass |

---

## Threats deliberately out of scope

Named rather than omitted, so their absence is a decision:

- **Prompt injection / model manipulation.** No LLM is in the tested path. The
  diligent agent is deterministic precisely so failures cannot be blamed on a
  model.
- **Network-level attack.** Everything binds to `127.0.0.1`; there is no
  adversary on the wire.
- **Credential theft.** ADR-002 records why local-only credentials are literal,
  and the boundary at which that stops being acceptable.
- **Denial of service.** Capacity behaviour is unmeasured. ADR-003 records the
  measured bottleneck (the oracle, 8 connections per verdict) and when to fix it.

---

## The threat this model exists to make visible

None of T1–T12 causes the failures in `docs/RESULTS.md`.

Every control above holds during `S1`, and the business state is still wrong by
$100. **The gap is not a threat to a control — it is the absence of any control
at that scope.** A threat model that only enumerates attacks on existing
mechanisms will never surface it, which is why the invariant catalog is a
separate document and not an appendix to this one.
