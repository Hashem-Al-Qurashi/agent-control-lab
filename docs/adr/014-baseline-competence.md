# ADR-014 — Why the baseline is competent, and how you can check

**Status:** accepted · **Date:** 2026-08-29

## The objection this exists to answer

*"You built a system with an obvious hole and then walked through it."*

It is the correct first reaction, and no amount of prose defeats it. If the
baseline is weak, `S1` demonstrates nothing except that weak systems fail.

So competence is not asserted here. **It is demonstrated by controls that pass** —
schedules that produce a clean verdict because the system genuinely handles the
thing being tested. Those tests are the load-bearing half of the repo, and they
are exactly as important as the ones that produce violations.

## What the baseline does correctly

| Property | Evidence |
|---|---|
| Every action authenticated by a signed token | `test_a_forged_token_is_rejected`, `test_a_token_signed_with_another_key_is_rejected` |
| Every action authorized against a scope | `test_a_missing_scope_is_rejected`, `test_scope_for_one_action_does_not_authorize_another` |
| Amount ceilings enforced per action | `test_above_threshold_without_approval_authority_is_rejected` |
| Tenant isolation as a hard deny | `test_a_cross_tenant_action_is_rejected` |
| Retries produce exactly one effect | `P3`, `test_same_idempotency_key_creates_exactly_one_row` |
| Redelivery does not double-count | `S5`, `test_s5_redelivery_does_not_move_the_projection` |
| Event ordering does not change the result | `S4`, `test_s4_reversed_apply_order_reaches_the_same_state` |
| Effect and event commit atomically | `test_event_and_effect_commit_atomically` |
| Failures surface rather than being swallowed | `test_server_error_surfaces_rather_than_being_swallowed` |
| Policy decisions are deterministic | `test_the_policy_is_deterministic` |

**`S6` is the sharpest one.** Both actors attempt, both are refused, nothing is
written and no event is published — `test_s6_proves_authorization_is_not_decorative`,
`test_s6_writes_nothing`. The authorization layer is real. It stops what it is
for. It simply is not scoped to the aggregate.

## The agent is diligent by construction

The failing agent is not careless. Before every action it reads **every system it
has access to**, sums what it observes, and declines when the action would breach
the ceiling. `test_declines_when_the_action_would_breach_the_ceiling`,
`test_declines_on_a_breach_spread_across_both_services`,
`test_acts_exactly_at_the_ceiling`.

It has no model in it, so no failure can be attributed to a hallucination, a
prompt or a bad tool choice (ADR-011). It has no application-level retry loop,
which would be indistinguishable from two agents racing (ADR-001). It does not
guess: `test_unknown_action_raises_rather_than_guessing`.

**It fails while doing everything correctly with what it was given.** That is the
claim, and it is only interesting because the preceding table is true.

## The strongest available rebuttal, and its answer

*"Then the agent should also read the authoritative stores instead of the
projection."*

Fair — and `S3` answers it. The projection partially catches up, the third actor
sees a **more current** view, and the aggregate is still breached:
`test_s3_third_actor_saw_a_partially_current_view`,
`test_s3_violates_despite_partial_catch_up`.

Freshness reduces the window. It does not close it, because no read closes a
window that stays open until a write lands somewhere else.

`test_agent_does_not_also_read_authoritative_stores_when_given_a_projection` pins
the honest limitation of `S1`: given a projection, that agent uses it. `S3` exists
so the finding does not rest on that choice.

## What actually fixes it, which is the point

Not diligence. Not freshness. **An authority that can see all the invariant's
inputs at decision time.**

Same interleaving, one control added:

- `P2` violates → `P0` clean (`test_the_contrast_in_one_assertion`)
- `S1` violates → `S1H` clean, with the projection **just as stale**
  (`test_s1h_projection_was_just_as_stale_as_in_s1`,
  `test_s1h_and_s1_differ_only_in_the_available_authority`)

Those two pairs are the argument. The staleness is unchanged, the agent is
unchanged, the schedule is unchanged, and the outcome flips — which locates the
cause in the **interface the agent was given**, not in the agent.

## How a skeptic should attack this

Named, because a defence that only lists its own strengths is not one:

1. **Check the negative controls actually ran.** `P1`, `S1C`, `S4`, `S5`, `S6`
   must pass, and `assert_schedule_executed` must hold. A suite where only the
   violations execute proves nothing.
2. **Check the oracle was calibrated first.** `make calibrate` — it must catch a
   planted violation and pass a planted safe state before any schedule runs.
3. **Try to make the diligent agent smarter.** Re-read immediately before the
   write, retry on conflict. `S3` predicts the window narrows and does not close.
4. **Check the databases are actually separate** (ADR-009). If they were not, the
   whole thing is a schema artifact.

If any of those fails, the finding is void. That is the intended reading.
