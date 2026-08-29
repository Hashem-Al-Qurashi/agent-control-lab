# ADR-004 — Two style findings deliberately not fixed

**Status:** accepted · **Date:** 2026-08-29

A standards pass produced three findings. One was real and fixed (two
over-length lines). The other two are declined, recorded here so the next person
does not "fix" them and make the code worse.

## 86 public functions without docstrings

Mechanically true. Most are trivial accessors — `pointer`, `is_complete`,
`waiters`, `leases`, `health`, `connect`. Their names already say everything
they do.

This codebase carries its reasoning in **module docstrings**, which are unusually
long and explain *why* each mechanism exists — why the barrier fails closed, why
the oracle writes its own SQL, why identity is a wire value. Adding
`"""Return the pointer."""` to eighty-six accessors would dilute that with noise
and train a reader to skip docstrings, which is precisely where the load-bearing
reasoning lives.

Docstrings were added only where they carry information a reader lacks — for
example `control.reserve`, where a 409 is a *normal outcome* rather than an
error, and nothing in the signature says so.

**Rule:** a docstring here must explain why or warn about a non-obvious
consequence. If it only restates the name, leave it out.

## Four functions over 50 lines

| Function | Lines | Why it stays whole |
|---|---|---|
| `coordinator.await_checkpoint` | 63 | The fail-closed path. A sequence of guard clauses that must be read as one unit — splitting scatters the logic guaranteeing no release is ever returned on an error path. |
| `pool._worker` | 66 | Everything constructed across the process boundary, in one place. Splitting hides what does and does not cross. |
| `policy.run_case` | 51 | The diligent policy read-check-write, deliberately linear. Its readability *is* the pre-registered definition of "diligent". |
| `runner.run_schedule` | 52 | Ordered steps whose order is the contract: clean, declare, dispatch, wait, assert quiescence, evaluate. |

Each is cohesive, heavily commented, and does one thing. Splitting them to
satisfy a line count would scatter exactly the code that most needs to be read
in one sitting.

**Rule:** length is a smell, not a defect. Split when a function does two
things, not when it crosses a number.
