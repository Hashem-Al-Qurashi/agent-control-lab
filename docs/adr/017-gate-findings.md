# ADR-017 — What the mandated thinking tools found

**Status:** accepted · **Date:** 2026-08-30

## Context

`/strict` mandates four thinking-pattern tools at Gates 0, 1, 3 and 4. They were
unavailable for most of this build — the server was configured under
`mcpServers` in `~/.claude/settings.json`, which Claude Code does not read for
MCP registration. `claude mcp list` never showed it. Re-registering it via
`claude mcp add -s user` fixed that, and the tools were then reachable from a
subprocess session.

The gates were then run for real. Two of the four produced findings that changed
the code, which is the argument for having run them.

## Gate 3 — `metacognitive_monitoring` returned 0.55, and the gate fails

`/strict` fails Gate 3 below 0.8. Four claims were assessed:

| Claim | Status | Confidence |
|---|---|---:|
| Reconciliation never detects the aggregate breach | inference | 0.60 |
| The authority grants exactly ten holds at 100 concurrent | inference | 0.55 |
| Reservation expiry is safe | **speculation** | **0.15** |
| The harness is deterministic | uncertain | 0.25 |

**This is the correct answer and it is recorded rather than argued with.**
"Expiry is safe" *should* score badly: `ACL-F18` demonstrates the expiry control
freeing already-spent budget. "The harness is deterministic" should score badly:
ADR-007 and ADR-015 are open.

Gate 3 does not pass. Reporting it as passed would be the exact defect this
repository exists to describe.

## Gate 1 — `critical_thinking` found a real hole in the catalogue guard

> *"Existence is not demonstration. The meta-test asserts a test with the cited
> name exists; it does not assert the test passes, that it is executed…"*

Correct. `tests/unit/test_failure_catalog.py` checked that a cited test **name**
appears in the source. A cited test could be skipped, xfailed, quarantined or
failing and the entry would still read **Reproduced here**. It also noted that
bare function names are ambiguous when two files define the same name, which is
true here.

### What it caught immediately

`catalog/verify.py` reads a real run's JUnit report and requires every cited
test to have **passed**. On first execution it failed, correctly:

```
ACL-F13: test_arm_c_reproduces_the_violation_with_a_real_model  outcome was ['skipped']
ACL-F14: test_every_span_in_the_breaching_run_reports_success   outcome was ['skipped']
```

Both entries claimed reproduction while their tests skip in a default run — one
gated behind `ACL_RUN_LLM` and a key, the other behind a live collector. A
reader running `pytest` would have seen skips under a heading saying
**Reproduced here**.

### The fix, which is disclosure rather than downgrade

Those entries are genuinely reproducible; they need opting in. So the schema
gained `requires:`, rendered into the page, and `verify.py` accepts a skip
**only** when the entry declares what it needs. An entry that skips silently is
still an overclaim. Mutation-verified: removing the `requires` field puts the
failure back.

## Gate 4 — `decision_framework` agreed, and named an untested case

Scored the reaper-inside-the-lock at 0.66 against a background-only reaper and
Temporal, recommending what was already built. Useful anyway for what it flagged:

> *"add a contended-expiry repro on an injected clock — expiry racing an
> in-flight acquisition, not just idle expiry."*

True. Every expiry test here reclaims an **idle** hold, and `CAPACITY.md` states
that every capacity run had zero holds to reclaim. Expiry racing a live
acquisition is unmeasured. Recorded as a known gap rather than quietly closed.

## Consequence

The two gates that were skipped longest are the two that found defects. That is
not evidence that process always pays — it is evidence that these two, on this
work, did.
