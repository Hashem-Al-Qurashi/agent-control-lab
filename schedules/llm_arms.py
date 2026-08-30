"""Arms C and D: the same two-agent workload, decided by a model.

Mirrors schedules/naturalistic.py deliberately. Same case, same amounts, same
ceiling, same concurrency -- the only difference is who decides. That is what
makes arm C comparable to Mode B's deterministic result, and arm D comparable
to S1H.

Mode B, not Mode A. A model chooses how many times to read and in what order, so
a declared checkpoint sequence would either abort on an undeclared occurrence or
constrain the model until it was the deterministic agent in costume.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal

from agents.diligent.clients import HttpServiceClient, ReservationClient
from agents.diligent.policy import CaseConfig
from agents.llm.policy import LLMClients, Transcript, run_case
from libs.barrier.middleware import actor_identity
from oracle.invariants import Verdict, evaluate


@dataclass(frozen=True)
class ArmRun:
    case_id: str
    verdict: Verdict
    committed_total: Decimal
    transcripts: tuple[Transcript, ...]
    errors: tuple[str, ...]


def _one(stack, case_id, actor, action, amount, ceiling, model, with_reservation):
    billing = HttpServiceClient(stack["billing"], "refunds")
    ledger = HttpServiceClient(stack["ledger"], "credits")
    control = ReservationClient(stack["control"]) if with_reservation else None

    clients = LLMClients(
        billing,
        ledger,
        model=model,
        **(
            {
                "reserve": control.reserve,
                "release": control.release,
                "commit": control.commit,
            }
            if control
            else {}
        ),
    )
    config = CaseConfig(
        case_id=case_id,
        actor_id=actor,
        schedule_id="LLM",
        action=action,
        amount=Decimal(amount),
        idempotency_key=f"{case_id}-{actor}",
        authorized_compensation=Decimal(ceiling),
    )
    # Identity must be bound or outbound_headers() refuses to forward it.
    with actor_identity(actor, "LLM"):
        try:
            return run_case(case_id, config, clients), None
        except Exception as exc:  # surfaced, never counted as a decline
            return None, f"{actor}: {type(exc).__name__}: {exc}"
        finally:
            billing.close()
            ledger.close()


def run_arm(stack: dict, case_id: str, model, with_reservation: bool,
            ceiling: str = "1000.00", amount_a: str = "600.00",
            amount_b: str = "500.00", stagger_seconds: float = 0.0) -> ArmRun:
    """Two model-driven agents on one case. Whatever happens, happens."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_one, stack, case_id, "A", "refund", amount_a,
                            ceiling, model, with_reservation)
        if stagger_seconds:
            time.sleep(stagger_seconds)
        second = pool.submit(_one, stack, case_id, "B", "credit", amount_b,
                             ceiling, model, with_reservation)
        results = [f.result() for f in (first, second)]

    transcripts = tuple(t for t, _ in results if t is not None)
    errors = tuple(e for _, e in results if e is not None)

    outcome = evaluate(case_id, Decimal(ceiling))
    return ArmRun(
        case_id=case_id,
        verdict=outcome.verdict,
        committed_total=outcome.committed_total,
        transcripts=transcripts,
        errors=errors,
    )
