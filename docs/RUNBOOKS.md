# Runbooks

One per alert that can actually fire. A runbook for an alert nobody wired up is
decoration; an alert with no runbook is a page to someone who does not know what
to do.

Each ends with the same question — **what would have caught this sooner** —
because a runbook that only restores service teaches nothing.

---

## RB-001 · Aggregate invariant breached

**Fires when:** the invariant checker reports a committed total above the
authorized amount.

**This is money, and it is already spent.** The effects are durable; nothing here
un-spends them.

1. **Do not roll back.** Reversing a committed effect requires a *new* authorized
   action. Deleting rows destroys the evidence and the audit trail.
2. **Scope it.** Which case, which actors, how much over. `SELECT` the effects for
   the case from each service — the oracle's own SQL is the query.
3. **Determine whether it is real or a rig defect.** Two effects sharing an
   idempotency key means broken idempotency, not a genuine breach — the oracle
   reports `INCONCLUSIVE` for exactly this. A real breach has distinct keys from
   distinct actors.
4. **Check whether a coordination authority existed for this path.** If not, this
   is not a bug in any service; it is a missing control. See `P0` / `S1H`.
5. **Reverse deliberately**, as a new authorized compensating action with its own
   idempotency key.

**What would have caught this sooner:** an invariant checker at a quiescence
point, separate from operational monitoring. Ordinary monitoring does not see
this — measured in `S1` and `S3`.

---

## RB-002 · Projection lag exceeds its bound

**Fires when:** unapplied events for a case exceed the reconciliation window.

1. **Assume agents are acting on stale data right now.** That is the operational
   risk, not the lag itself.
2. **Is the projector running?** No consumer is the common cause.
3. **Is it stuck on one event?** A poison event blocks everything behind it, since
   application is ordered.
4. **Is the lag growing or flat?** Growing means the consumer cannot keep up; flat
   means it stopped.
5. **Consider pausing agents that read the projection** until it catches up.
   Declining is safe; acting on a stale view is not.

**What would have caught this sooner:** a bound on the lag at all. "Eventually
consistent" without a stated window is not a property.

---

## RB-003 · A reservation hold is stuck

**Fires when:** a hold has been `HELD` well beyond any plausible action duration.

**This one looks like the control working.** Legitimate actions are being refused
against budget nothing occupies, and the refusals are correct-looking 409s.
Nobody investigates a working control — which is why this needs an alert rather
than a dashboard.

1. **Find the holder and whether its action landed.** A committed effect with a
   still-held reservation means the commit call was lost.
2. **If the effect landed:** commit the hold. The budget is genuinely spent.
3. **If it did not:** release the hold. Release is idempotent.
4. **Never release a hold whose effect committed** — that frees budget already
   spent, and the next actor will breach the ceiling legitimately.

**What would have caught this sooner:** hold expiry. There is none — T9, and
trigger 2 in ADR-006 for adopting durable execution.

---

## RB-004 · Replay determinism failed

**Fires when:** P4 reports a schedule replaying differently.

**Stop. Publish nothing.** No verdict from this rig is reproducible until this is
understood, and a violation cannot be told from scheduling luck.

1. **Do not dismiss it as flakiness.** It is the failure most tempting to
   re-run until green.
2. **Capture the diff before anything else.** It disappears once the environment
   changes — this happened, see ADR-007.
3. **Check for orphaned services** from a previous run. `pgrep -f 'uvicorn apps\.'`
   — the session fixture now refuses to start if any exist.
4. **Check the barrier**: checkpoint placement relative to commit, actor scoping,
   occurrence indices.
5. **Check the server concurrency model.** A single worker serialises actors and
   changes what a schedule does.

**What would have caught this sooner:** the orphan guard, which now exists
because of ADR-007.

---

## RB-005 · Rejections surfacing as 5xx

**Fires when:** authorization or validation failures return server errors.

Lower severity, higher confusion. An abuse attempt indistinguishable from an
outage means dashboards cannot tell an attack from a bad deploy, and an agent
cannot tell *"you may not"* from *"try again later"* — so it retries something it
was never permitted to do.

1. Find where the rejection is raised. A 500 usually means it reached a database
   constraint instead of a boundary validator.
2. Move the check to the boundary. The constraint stays as defence in depth.
3. Confirm nothing was written on the rejected path.

**What would have caught this sooner:** the abuse suite, which found exactly this
on its first run — negative amounts reaching the `CHECK` constraint.
