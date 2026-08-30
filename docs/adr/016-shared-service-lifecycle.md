# ADR-016 — One implementation of service spawning

**Status:** accepted · **Date:** 2026-08-30

## Context

`demo/harness.py` needed to start the coordinator and three services, wait for
them, and stop them. `tests/schedules/conftest.py` had done exactly that for
weeks. I wrote a second implementation instead of looking, and it reintroduced
two bugs the first one had already solved:

1. **The coordinator was spawned with four workers.** It holds the schedule
   pointer and its parked waiters in process memory, so the declare landed on
   one worker and the awaits on another. The symptom was `no schedule declared`
   from a coordinator that was running perfectly.
2. **It waited on `/health`, which the coordinator does not have.** The wait
   loop polled a 404 until it gave up.

A third bug was worse and was not a duplication issue: the coordinator was
spawned *before* the `try`, so a failed startup leaked it. Three accumulated and
tripped ADR-007's orphan guard, erroring 65 unrelated tests.

## Decision

Extract spawning, readiness and shutdown into `libs/servicelab.py`. Both the
test fixtures and the demo use it. The two constraints that caused the bugs are
encoded as named constants next to the code that applies them —
`COORDINATOR_WORKERS = 1` and `COORDINATOR_READY_PATH = "/waiters"` — rather than
living as knowledge in one file that a second file cannot see.

## Alternatives considered

**Leave the duplication.** Two callers is not much duplication, and the demo's
needs could diverge. Rejected on evidence rather than principle: the duplication
had *already* cost two bugs within an hour of existing, and the divergence it
was supposed to permit was entirely accidental.

**Have the demo import the test conftest.** `tests/` is not a package —
`ModuleNotFoundError` — and a production demo importing test fixtures inverts
the dependency. Rejected.

**Move it into the schedules runner.** The runner orchestrates a schedule
against a stack that already exists; it does not own process lifecycle. Putting
it there would give the runner a second responsibility. Rejected.

## Consequences

**Positive.** One place to fix a lifecycle bug. The coordinator's two
constraints are now stated where they are enforced. `on_spawn` / `on_stop`
callbacks let the test fixtures keep their ownership tracking (`libs/procguard`)
without the demo needing it.

**Negative.** `libs/` now contains something only the harness and the demo use,
which slightly blurs "libs is for the services". The alternative was a third
top-level directory for one module.

**Risk.** Changing the shared spawner now affects the entire schedules suite.
Mitigated by the suite itself: 479 tests exercise it, and the extraction was
verified by running all of them before and after — same count, same result, zero
orphaned processes.

## What this is really a record of

Not a refactor. A note that the `search-first` question — *does this already
exist in the repo?* — was skipped, and what that cost. The bugs were not subtle
consequences of duplication; they were the original bugs, verbatim, rediscovered.
