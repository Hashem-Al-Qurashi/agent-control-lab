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
