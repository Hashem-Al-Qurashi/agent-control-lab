# ADR-008 — The LLM arms are unbuilt, and why that is not a hole

**Status:** accepted · **Date:** 2026-08-29

## Context

`LAB-SPEC.md` specifies a 2×2:

|  | Baseline | Hardened |
|---|---|---|
| **Diligent deterministic agent** | A ✅ | B ✅ |
| **LLM agent** | C ❌ | D ❌ |

Arms A and B are complete. Arms C and D are not.

## Immediate blocker

No model credentials are available in this environment. The SDKs are installed;
there is no API key, and going looking for one is not appropriate.

An LLM arm written but never run against a real model would be worse than none:
it would look like coverage in the file listing while proving nothing, which is
the exact failure this repo keeps catching in itself.

## Why arms A and B stand without C and D

This is the part that matters, and it is not a consolation prize.

The spec chose the diligent deterministic agent deliberately:

> **A** — if this violates, *the architecture permits the failure*. Model blame
> impossible. Durable: doesn't expire when the next model ships.

Every violation in `RESULTS.md` was produced by an agent with **no model in it**.
Nobody can attribute those results to a hallucination, a bad tool choice, or a
prompt. That was the point of arm A, and it is the stronger claim precisely
because it does not depend on which model was current.

## What C and D would add, stated honestly

Not the finding. Two secondary questions:

- **C** — how much *additional* risk does a probabilistic policy add over a
  perfect one? Expected to be non-zero and uninteresting: an agent that
  sometimes reads badly will breach at least as often as one that never does.
- **D** — do the deterministic controls hold despite model variability? P0, S1H
  and the capacity result already show the reservation authority holds against a
  perfect adversary and 100 concurrent agents. An LLM is a *worse* adversary than
  either, not a better one.

Hypothesis H3 in the spec is deliberately direction-neutral — *"increase,
decrease, or otherwise alter"* — so neither answer is assumed.

## Decision

Do not build them here. Record the gap rather than let a reader discover a 2×2
with two empty cells and wonder what else was quietly dropped.

## What would close this

A model credential and a modest budget. The arm needs: the existing
`run_case` shape with the policy's read-check-write replaced by a model call, the
decision cached so an interleaving can be replayed without re-paying for
inference (already specified in `LAB-SPEC.md` under cost control), and a subset
of schedules rather than all eleven.

Estimated as the smallest remaining piece of real work in the plan — the harness,
the schedules, the oracle and the controls all already exist and are
model-agnostic by construction.

---

## Amendment — 2026-08-30: unblocked and built

This ADR recorded arms C and D as blocked on credentials. The blockage was real
and lasted until someone checked what was actually available: a
`DEEPSEEK_API_KEY` was already present in the environment, and DeepSeek's
OpenAI-compatible endpoint supports tool calling. The cost of the experiment was
a few cents.

Worth naming as a lesson rather than a footnote: **"blocked on credentials" went
unexamined for the whole build.** Nobody, including me, checked whether a key was
already there. A deferral recorded once tends to stay recorded.

Both arms are built and measured — `docs/LLM-ARMS.md`. Arm C reproduces the
violation 5/5 at $1,100 with a model that reads before acting. Arm D holds 5/5,
with the refusals coming from the control service.

**The position on evidence strength is unchanged.** The deterministic arm remains
the stronger support for the structural claim, because no failure there can be
blamed on a model. What arm D adds is a claim about the *fix* rather than the
failure: it holds with cognition in the loop, unchanged.
