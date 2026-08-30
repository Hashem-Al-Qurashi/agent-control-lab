# Arms C and D — the same workload, decided by a model

```
ACL_RUN_LLM=1 ACL_LLM_RUNS=3 make test-llm
```

Gated twice — an explicit flag *and* a key — so an ordinary run never spends
money and never depends on a third party being reachable.

---

## What these arms are for

Stated before the results, because it is the part most easily oversold.

**The deterministic arm remains the stronger evidence for the structural claim.**
With no model in the path, no failure can be blamed on a hallucination or a
prompt. Adding a model does not make that claim stronger; it makes it easier to
dismiss. That reasoning is unchanged by these results.

These arms answer a **different** question:

- **Arm C** (no coordination authority) — does the finding survive real
  cognition, or was it an artifact of an agent that is just arithmetic?
- **Arm D** (with the authority) — does the control hold something that is *not*
  arithmetic? If it does, **the fix is cognition-independent**, which is a
  stronger statement about the fix than the deterministic arm can make.

Arm D is the one worth having.

## Setup

Identical to Mode B: one case, a $1,000 ceiling, agent A issuing a $600 refund
and agent B a $500 credit, launched concurrently. If both act, the total is
$1,100. Model: `deepseek-chat`, `temperature=0`, tools for reading compensation,
issuing, declining, and — in arm D only — reserving budget.

The prompt states the ceiling and states that it spans both systems. The model
is not told the answer, and **nothing in the harness prevents it from
exceeding the ceiling** — a scaffolding that refused on the agent's behalf would
be measuring itself.

## Results

Five runs per arm.

| Arm | Verdicts | Committed totals |
|---|---|---|
| **C** — no authority | **5/5 VIOLATION** | $1,100.00 every run |
| **D** — with authority | **5/5 CLEAN** | $500, $500, $600, $500, $500 |

**Arm C reproduces the finding exactly.** In every run both agents called
`read_compensation` *first*, both saw the pre-write state, and both issued. The
model was diligent in the same sense the deterministic policy is diligent — it
established the facts before acting — and it was wrong anyway, for the same
reason: its read and its write are not atomic across two services.

That the totals are identical to the deterministic arm's ($1,100, five times) is
the point. Cognition changed nothing, because cognition was never the problem.

**Arm D held every time.** The control refused whichever agent lost the race and
the other proceeded. Which agent wins varies — run 2 went to A for $600, the rest
to B for $500 — and that variation is exactly why these arms run in Mode B and
not in the scripted Mode A schedules.

A detail worth recording: on refusal the model **re-read and then declined.** It
did not attempt to issue anyway.

## Why Mode B and not a schedule

Mode A requires a declared, deterministic sequence of checkpoint arrivals. A
model chooses how many times to read and in what order, so scripting it would
either abort the run on an undeclared occurrence or constrain the model until it
was the deterministic agent in costume. Neither is an experiment. Frequency over
repeated naturalistic runs is the honest measurement.

`temperature=0` is reproducibility as far as the provider offers it. It is not
determinism and is not claimed as such.

## What arm D does not prove

The harness refuses an `issue` that was never reserved, standing in for a service
that would require one — the billing service here does not check reservations.
So arm D is **not** a test of whether a model would bypass the control if the
service let it.

What makes the result meaningful anyway is that the refusals came from the
**control service**, not the scaffolding, and a test asserts exactly that
(`test_arm_d_refusals_come_from_the_control_not_the_harness`). Without that
assertion, arm D's cleanliness could be my own code refusing on the model's
behalf, which would prove nothing.

## Limits

- **One model, one provider, one prompt.** A different model may behave
  differently in arm C. Arm D should not, because the control does the work.
- **Five runs.** Enough to say the effect is not marginal, not enough for a rate.
- **One machine, local services, no network latency.** Same limit `MODE-B.md`
  states.
- **The prompt is a variable.** A prompt that failed to mention the ceiling
  spanned both systems would make arm C's violation the prompt's fault. A test
  pins that the prompt says it (`test_the_ceiling_is_stated_to_the_model_as_spanning_systems`).

## The sentence this earns

> The failure reproduces with a real model that reads before it acts, and the
> coordination authority prevents it with the same model unchanged. The control
> does not depend on what is doing the deciding.
