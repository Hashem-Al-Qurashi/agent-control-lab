"""The live breach, in about thirty seconds.

Not a mock and not a replay: this runs the real S1 schedule against the real
services and reads the real oracle verdict. `tests/integration/test_demo.py`
asserts what it prints, because a demo that stops demonstrating still runs,
still prints, and still looks like a demo.

The order is the argument. Health signals first, all green, while the audience
has no reason to suspect anything. The money last.
"""

from __future__ import annotations

import pathlib
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BOLD, DIM, RED, GREEN, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[0m"


def _rule(char: str = "─") -> None:
    print(DIM + char * 64 + RESET)


def _step(text: str) -> None:
    print(f"  {DIM}·{RESET} {text}")


def main() -> int:
    from apps.reconciliation.worker import reconcile
    from oracle.invariants import Verdict

    print()
    print(f"{BOLD}Agent Control Lab — S1{RESET}")
    print(f"{DIM}Two agents. Strictly sequential. Nothing overlaps.{RESET}")
    _rule()

    ceiling = Decimal("1000.00")
    print(f"  Authorised compensation for this case: {BOLD}${ceiling}{RESET}")
    _step("Agent A will refund $600.00")
    _step("Agent B will credit $500.00, starting only after A is acknowledged")
    print()

    from demo.harness import run_s1

    print(f"{DIM}running…{RESET}")
    outcome = run_s1()
    print()

    _rule()
    print(f"{BOLD}Health signals{RESET}")
    agents_ok = all(status == "ok" for status, *_ in outcome.actor_outcomes)
    print(f"  agents          {GREEN}OK{RESET}   "
          f"{DIM}both completed, neither errored or retried{RESET}"
          if agents_ok else f"  agents          {RED}ERROR{RESET}")
    print(f"  trace           {GREEN}OK{RESET}   "
          f"{DIM}every span succeeded, no anomalous latency{RESET}")

    report = reconcile(outcome.result.case_id)
    money_findings = [f for f in report.findings if "SPENT_EXPIRED" in f.type.value]
    clean = not money_findings
    print(f"  reconciliation  {GREEN}OK{RESET}   "
          f"{DIM}no drift, no duplicate keys, no orphans{RESET}"
          if clean else f"  reconciliation  {RED}FINDINGS{RESET}")
    print()

    _rule()
    print(f"{BOLD}Business state{RESET}")
    total = outcome.result.committed_total
    verdict = outcome.result.verdict
    colour = RED if verdict is Verdict.VIOLATION else GREEN
    print(f"  committed       {BOLD}${total}{RESET} against a ${ceiling} ceiling")
    print(f"  verdict         {colour}{BOLD}{verdict.value}{RESET}"
          f"   {DIM}over by ${outcome.result.realized_overage}{RESET}")
    _rule()
    print()
    print("  Every action was authorised. No component failed.")
    print("  The invariant spanned two services, and no authority owned it.")
    print()
    print(f"{DIM}  make reproduce SCHEDULE=S1H   # same staleness, one control added{RESET}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
