"""Mode B -- naturalistic stress. Barriers off, nobody choosing the order.

Mode A answers "can this execution happen, and why". It cannot answer "how
often", because the interleaving is chosen. Mode B answers frequency and nothing
else: it makes no reproducibility claim and cannot explain any single run.

Integrity rules, from LAB-SPEC, because this is where a frequency number is
easiest to manufacture:

  * workload parameters (concurrency, count) may be tuned and MUST be reported
  * artificial delays may NOT be injected -- that is Mode A wearing a disguise
  * the oracle must not perturb: it reads after the run, never during
  * if zero violations occur, that is the result and it gets published

The window-opened observable exists because a violation frequency alone is
uninterpretable. "0.4% of runs breached" means nothing without knowing the race
window opened at all -- 0.4% of runs where the window never opened would indicate
a completely different problem.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal

import httpx
import psycopg2

from oracle.invariants import Verdict, evaluate
from oracle.quiescence import OWNER_DSNS


@dataclass(frozen=True)
class NaturalRun:
    case_id: str
    verdict: Verdict
    committed_total: Decimal
    window_opened: bool


def _act(stack: dict, case_id: str, actor: str, action: str, amount: str,
         ceiling: str) -> None:
    """One agent: read everything it can, then act if the invariant still holds.

    Deliberately mirrors the diligent policy rather than importing it -- the
    policy's checkpoint hooks are Mode A machinery and have no place here.
    """
    headers = {"X-Actor-Id": actor, "X-Schedule-Id": "MODEB"}
    with httpx.Client(timeout=60.0, transport=httpx.HTTPTransport(retries=0)) as c:
        observed = Decimal("0")
        for base, collection in (
            (stack["billing"], "refunds"),
            (stack["ledger"], "credits"),
        ):
            r = c.get(f"{base}/{collection}", params={"case_id": case_id},
                      headers=headers)
            observed += Decimal(r.json()["total_committed"])

        if observed + Decimal(amount) > Decimal(ceiling):
            return

        base = stack["billing"] if action == "refund" else stack["ledger"]
        collection = "refunds" if action == "refund" else "credits"
        c.post(
            f"{base}/{collection}",
            json={"case_id": case_id, "amount": amount,
                  "idempotency_key": f"{case_id}-{actor}"},
            headers=headers,
        )


def _window_opened(case_id: str, stack: dict) -> bool:
    """Did the second actor read before the first actor's write completed?

    Derived from request_log, which records each request's actor and its start and
    end on the server. No extra instrumentation, and nothing that could perturb
    the run.
    """
    reads: list[tuple[str, float]] = []
    writes: list[tuple[str, float]] = []
    for service in ("billing", "ledger"):
        conn = psycopg2.connect(OWNER_DSNS[service])
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT actor_id, method, started_at, ended_at FROM request_log "
                    "WHERE schedule_id = 'MODEB' AND ended_at IS NOT NULL"
                )
                for actor, method, started, ended in cur.fetchall():
                    if method == "GET":
                        reads.append((actor, started.timestamp()))
                    elif method == "POST":
                        writes.append((actor, ended.timestamp()))
        finally:
            conn.close()

    # The window is open when one actor's read begins before a DIFFERENT actor's
    # write has finished -- that read cannot see that write.
    for read_actor, read_start in reads:
        for write_actor, write_end in writes:
            if read_actor != write_actor and read_start < write_end:
                return True
    return False


def run_naturally(stack: dict, case_id: str, ceiling: str = "1000.00",
                  amount_a: str = "600.00", amount_b: str = "500.00",
                  stagger_seconds: float = 0.0) -> NaturalRun:
    """Two agents, no coordination, no schedule. Whatever happens, happens.

    `stagger_seconds` separates the agents' ARRIVAL, which is a workload
    parameter -- how far apart two requests reach the system. The integrity rules
    permit tuning workload and require reporting it.

    It is not an injected delay inside the system under test. Nothing is paused
    mid-transaction, no checkpoint is held, and neither service behaves
    differently. That distinction is the whole line between Mode B and Mode A
    wearing a disguise: Mode A controls what the system does, Mode B controls
    only when the agents show up.

    Measuring across staggers matters because at zero separation the race window
    is open essentially always, which measures the workload rather than the
    phenomenon.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_act, stack, case_id, "A", "refund", amount_a, ceiling)
        if stagger_seconds:
            time.sleep(stagger_seconds)
        second = pool.submit(_act, stack, case_id, "B", "credit", amount_b, ceiling)
        for f in (first, second):
            f.result()

    # Evaluated after both actors are terminal. The oracle never runs during.
    result = evaluate(case_id, Decimal(ceiling))
    return NaturalRun(
        case_id=case_id,
        verdict=result.verdict,
        committed_total=result.committed_total,
        window_opened=_window_opened(case_id, stack),
    )
