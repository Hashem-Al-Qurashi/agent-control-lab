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

---

## Update — 2026-08-30 (later): the reproduction was attempted, and it failed

The section above ends by naming the experiment that would close this. It was
then run, and it did not reproduce the divergence.

**Method:** revert `natural_stack` to `session` scope — recreating the exact
overlap condition, using only that scope change and no guard bypass — then run
`test_mode_b.py` followed by `test_p4_determinism.py` with `ACL_REPLAYS=20`, so
the Mode B services are live on the same databases throughout every replay.

**Result:** 2 runs. 20 replays × 4 schedules each. **No divergence.**

### What this does to the hypothesis

It weakens it. The measured overlap is real and the mechanism is plausible, but
the condition has now been recreated deliberately and the anomaly did not
follow. A cause that cannot be made to produce its effect on demand is a
suspect, not an explanation.

Stated plainly because it is the outcome most tempting to leave out: **the update
above found a satisfying story, and the experiment that would have confirmed it
did not.** The tidy narrative — session-scoped fixture, same databases, P0 and P2
specifically — survives as a coincidence that has not been shown to be more than
one.

Sample size is the honest limit in both directions. The original divergence was
seen **once**, in an unknown number of prior runs; the reproduction attempt is
**two** runs. Two failures to reproduce a once-seen event is weak evidence
against, just as one coincidence is weak evidence for.

### Why the scope change stays anyway

It is correct independent of the anomaly. A determinism claim should not depend
on which other fixtures happen to be alive, and two multi-worker services sharing
the databases under measurement is co-tenancy nobody chose. Removing it is
hygiene, and this ADR no longer presents it as a fix.

### Still open, and now with less of an explanation than it appeared to have

Unchanged: the original diff was never captured, so nothing can be attributed to
it after the fact. What would close this remains a divergence that recurs with
its diff captured. Everything else is a story about a thing that happened once.

---

## Update — 2026-08-30 (third): what 20 replays actually establishes

Gate 3's `metacognitive_monitoring` scored the claim "the harness is
deterministic" at 0.25, and its reasoning included a statistical point this ADR
had not made:

> 20 replays bounds flake rate only to roughly **<14% at 95% confidence**.

That is correct and it changes how every replay result in this repository should
be read. Twenty passing replays do **not** establish determinism. They establish
that the divergence rate is probably under about one in seven. An intermittency
that fires one run in fifty would pass twenty replays comfortably — and both
anomalies on record fired approximately that rarely.

So the accurate claim is: **the harness replays identically across the samples
taken, and the sample is too small to bound a rare intermittency.** Wherever
this repo says schedules "replay identically", read it with that bound attached.

Raising `ACL_REPLAYS` is the cheap way to tighten it — 200 replays would bound
the rate near 1.5% — and nobody has run that. It is the obvious next experiment
and it has not been done.

## A hypothesis worth testing: one defect, two symptoms

The same review noted that ADR-007 and ADR-015 may not be independent.

Both appear only in **multi-schedule runs** and never in isolation. Both involve
a schedule failing to complete its declared interleaving — ADR-007 as a replay
divergence, ADR-015 as a `ScheduleNotExecuted` where a projector's final
checkpoint is never reached. Both were unreproducible on demand. Neither
survived a clean single-schedule run.

That is a plausible single cause with two presentations, and treating them as two
separate mysteries may be what has kept both open. It also suggests the fault may
live in the **aggregate runner** — the fixture and truncation sequence shared
across schedules — rather than in the barrier or the services, which is a much
smaller place to look.

Not investigated. Recorded so the next attempt starts from a better hypothesis
than either ADR had alone.

---

## Update — 2026-08-30 (fourth): reproduced, under a named condition

The anomaly has been reproduced. A controlled pair at `ACL_REPLAYS=100`:

| Condition | Result |
|---|---|
| The full integration suite running concurrently against the same databases | **2 of 5 schedules diverged** — `P0`, `P1` |
| Nothing else touching the databases | **5 passed**, 100 replays each |

Both runs took ~11 minutes and differed only in whether another process was
writing to and truncating the same Postgres instances.

### Why this succeeds where the earlier attempt failed

The August 30 attempt above restored `natural_stack` to session scope and did
**not** reproduce it. That test was weaker than it looked: session scope left two
**idle** extra services holding connections. This run had a second process
actively inserting, truncating and reading across all five databases.

So the refined finding is narrower and more useful than "contention":

> **Idle co-tenancy does not reproduce it. Concurrent writes and truncations
> against the same databases do.**

That is consistent with the original sighting, which happened during a full-suite
run — the one context where another suite is actively using the same databases.

### Why 100 replays and not 20

Gate 3's statistical point is what made this findable. Twenty replays bounds the
divergence rate only to roughly 14%; the anomaly fires far more rarely. Every
earlier attempt to reproduce it used twenty. The sample was too small the whole
time, and no amount of repeating it at that size would have helped.

### What this still does not establish

**One paired observation, not a series.** N=1 at the run level in each condition,
albeit 500 replays within each. It should be repeated before the mechanism is
treated as settled, and the actual divergence diff was again not captured — the
failing run was the contaminated one, and its output was summarised rather than
kept.

The concrete mechanism also remains unidentified. "Another process is writing to
the same database" is a condition, not an explanation: what specifically about
that changes an application-level checkpoint ordering has not been traced.

### Consequence, and it is actionable

The determinism suite must not run concurrently with anything else touching
these databases, and this is now the documented reason. That is a real
constraint on how the suite is run, not a precaution — and it is exactly the
kind of dependency that was invisible while the anomaly was unexplained.

**Status stays OPEN**, with a materially better hypothesis than it has had at any
point: reproducible under active database concurrency, absent without it,
mechanism untraced.

---

## Update — 2026-08-30 (fifth): the diff, at last — and it retracts the update above

The divergence diff has finally been captured, and it says something different
from what the previous update concluded. **That update overclaimed and is
retracted.**

Deliberate reproduction: a load process writing to Billing and truncating
Billing and Ledger every forty writes, while 100 replays of each schedule ran.
All five failed. The captured diff for `P0`, replay 54 against replay 0:

```
replay 0:  verdict CLEAN, committed_total 600.00,
           release_order [8 checkpoints, in declared order],
           decision_log [('1','A','billing',None,'COMMITTED','600.00')], parked []

replay 54: verdict CLEAN, committed_total 600.00,
           release_order [8 checkpoints, IDENTICAL],
           decision_log [], parked []
```

pytest's own summary: **"Omitting 4 identical items"**. Verdict, committed total,
`release_order` and parked waiters matched exactly. `P1` shows the same shape.

### What that means

**The schedule replayed identically.** `release_order` is the barrier's own
record of which actor was released at which checkpoint in what order — the thing
determinism is actually about — and it was the same every time. The scheduling
was never nondeterministic in any of these runs.

The only field that differed was `decision_log`, and it differed by being
**empty**. My load process truncates the tables the fingerprint reads. So the
"divergence" is my own load generator deleting the evidence between the run and
the fingerprint read.

### The previous update was wrong, and probably wrong twice

The fourth update claimed the anomaly was "reproduced under active database
concurrency". That reproduction used the integration suite as the concurrent
load — and the integration fixtures truncate Billing and Ledger between tests.
Same mechanism. **That was almost certainly the same artifact**, and I recorded
it as a reproduction because the failure was satisfying rather than because the
diff had been examined. The diff had not been captured then either.

### The mechanism, named

> A process truncating these tables between a schedule's run and its fingerprint
> read empties `decision_log`, and the determinism test reports that as a replay
> divergence. It is a **fingerprint-stability** problem, not a scheduling one.

This very likely explains the original sighting too: it happened during a
full-suite run, where other suites truncate the same tables.

### What follows

The determinism claim is **stronger** than this ADR has ever stated, not weaker:
across 500 replays under hostile concurrent load, the barrier's release order
never varied once.

What is unsound is the fingerprint, which reads mutable tables another process
can empty. The fix is to make the fingerprint robust — capture it inside the run,
or treat an empty `decision_log` as an aborted sample rather than a divergence —
and that has not been done.

**Status: still OPEN**, but for a different and much smaller reason than when
this ADR was written. Not "scheduling may be nondeterministic" — the evidence now
says it is not. Rather: "the determinism test can report a divergence that is an
artifact of its own measurement." An instrument problem, in an ADR that spent its
life suspecting the system.

---

## Update — 2026-08-30 (sixth): resolved, and the answer was the instrument

The fifth update named the mechanism and proposed moving the decision-log read
inside the run. That was **implemented and did not work**, which is worth
recording because it is what produced the real answer.

With the read captured inside `run_schedule`, the same hostile load still
produced 5 failures — with the diff now *inverted* (replay 0 empty, replay 1
populated). Moving the read only narrows the window; it cannot close one that an
external process can open at any point during the run.

### The actual resolution

No fingerprint placement is safe against another process truncating the tables.
So the instrument stops trying to be immune and starts **telling the two apart**:

```
CorruptSample: replay 2: 600.00 committed but no transitions recorded.
Something truncated decision_log during the run -- this sample is destroyed,
not divergent. Run the determinism suite alone.
```

Two checks, because one was not enough. The first catches money committed with
no transitions recorded. That missed the case where the load truncated *both*
tables, leaving a sample that is internally consistent — zero committed, empty
log — and therefore invisible to any self-consistency test. The second compares
against the reference replay: a run recording nothing where replay 0 recorded
something did not behave differently, it lost its evidence.

### Measured

| Condition | Before | After |
|---|---|---|
| Clean | 5 passed | **7 passed** |
| Hostile concurrent truncation | 5 "divergences" | **6 corruption reports, 0 divergences** |

### What is now established

**The barrier is deterministic.** Across roughly 700 replays, including several
hundred under a process actively writing to and truncating the same databases,
`release_order` — the record of which actor was released at which checkpoint in
what order — never varied once. Not in a single observed sample.

Every "divergence" this ADR ever recorded was the measurement losing its
evidence. The ADR spent its life suspecting the scheduler and the scheduler was
never at fault.

### What this is not

The guard is **diagnosis, not immunity**. A sufficiently destructive concurrent
process can still leave a sample that looks plausible, and no in-process check
can rule that out. Isolation remains the precondition — `make determinism` says
so — and the guard exists to make a violated precondition legible instead of
looking like a scientific finding.

**Status: CLOSED as an anomaly, and the remaining constraint is documented.** Not
"the harness may be nondeterministic" — the evidence says firmly otherwise — but
"the determinism suite requires exclusive access to these databases, and now
says so when it does not have it."
