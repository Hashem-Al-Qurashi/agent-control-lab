# ADR-007 — An observed, unreproduced determinism anomaly

**Status:** open · **Date:** 2026-08-29

Recorded rather than closed. The project's own rule is that a divergence in
replay determinism invalidates the method and must not be explained away, so
"it went away" is not an acceptable ending.

## What was observed

One full-suite run reported:

```
FAILED tests/schedules/test_p4_determinism.py::test_schedule_replays_identically[P0]
FAILED tests/schedules/test_p4_determinism.py::test_schedule_replays_identically[P2]
3 failed, 264 passed
```

P0 and P2 replays produced different normalised transition sequences. Per
`ENGINEER-BRIEF.md`, that is the anomaly that invalidates everything: if the same
declared schedule does not replay identically, no verdict is reproducible and a
violation cannot be told from scheduling luck.

## What reproduction attempted

| Attempt | Result |
|---|---|
| `test_schedule_replays_identically[P2]` alone | passed |
| `tests/schedules` in order (53 tests) | passed |
| `tests/integration` + determinism test (127) | passed |
| Full suite, `--tb=long` to capture the diff | **276 passed** |

The divergence text was never captured. By the time the run was instrumented to
print it, the failure had stopped occurring.

## Leading hypothesis

The failing run began while orphaned `uvicorn` workers from an earlier killed
suite were still alive. That earlier suite had hung (see the pool-crash fix) and
was terminated with `pkill`, which did not reap every worker — 30 were counted
afterwards and cleared manually.

Those processes do not act on their own. They do hold Postgres connections and
consume CPU, and the oracle already opens 8 short-lived connections per verdict
(ADR-003). Under that contention, timing-sensitive behaviour plausibly diverges.

**This is a hypothesis. It was not confirmed**, because the anomaly did not
recur once the environment was clean.

## What changed as a result

A guard, not a fix. `tests/schedules/conftest.py` now fails at session start if
any `uvicorn apps.*` process is already running, with the command to clear them.

The reasoning: a determinism claim that quietly depends on a clean machine is
weak, and a polluted environment silently produces unreproducible results —
exactly the failure this harness exists to make impossible. Verified: the guard
fires when an orphan exists and passes when none does.

## What would close this

- The divergence recurring on a clean machine, with its diff captured. That
  would make it a real defect with a locatable cause.
- Or a deliberate reproduction: start orphaned workers, run the determinism
  suite, and observe divergence. That would confirm the hypothesis and turn the
  guard from a precaution into a documented mitigation.

Until one of those happens this stays **open**. An unexplained divergence that
stopped happening is not the same as one that was understood.

---

## Update — 2026-08-30: the contention was in the harness, and it was ours

The hypothesis above blamed *orphaned* processes from a previous run. That was
the wrong suspect, and looking for it produced a guard that could not have worked.

`natural_stack` — the Mode B fixture — was **session-scoped**. It spawns two
multi-worker services against the **same billing and ledger databases** the
schedules use. `test_mode_b.py` collects first, so those two services stayed
alive for the entire rest of the session: through P0, then P1, then P2.

**P0 and P2 are exactly the two schedules recorded above as diverging.**

Measured rather than argued, by sampling live `uvicorn apps.*` processes during
a run of `test_mode_b.py` followed by `test_p2.py`:

| `natural_stack` scope | Peak concurrent service processes |
|---|---:|
| `session` (the behaviour when the anomaly was seen) | **7** |
| `module` (now) | **5** |

Five is the schedules stack alone. The extra two were Mode B's, running
alongside every schedule that followed and competing for the same databases and
CPU — the precise condition the original hypothesis described, sourced from the
harness rather than from a previous run.

### The guard was worse than useless

It compared a bare `pgrep` against nothing, so it could not distinguish "left by
a previous run" from "started by this session." It therefore did **not** fire on
the real overlap — the two fixtures were both this session's — while it *did*
fire spuriously once both session-scoped fixtures existed, erroring 53 tests that
each passed in isolation.

So the guard alarmed on the harmless case and stayed silent on the actual one.
Ownership tracking fixed the false alarm (`libs/procguard.py`), and **that fix
alone would have made things worse**: teaching the guard to recognise those
processes as ours would have permanently silenced the only signal pointing at
real contention. Module scope removes the contention itself.

### Still open

This is a **candidate cause with a measured mechanism**, not a confirmed one. The
original divergence diff was never captured, so it cannot be attributed to
anything after the fact. The deliberate reproduction named above — run the
determinism suite under induced contention and observe divergence — remains the
thing that would close this, and it has not been done.

20 replays across all five schedules pass on a clean machine with the overlap
removed. That is consistent with the explanation and does not establish it.
