"""Arms C and D: the same workload, decided by a real model.

Gated twice -- ACL_RUN_LLM=1 and a key -- so a normal run never spends money and
never depends on a third party being reachable.

What these arms do and do not add. The deterministic arm remains the stronger
evidence for the structural claim, because a failure there cannot be blamed on a
hallucination or a prompt. These answer a different question: does the finding
survive real cognition, and does the FIX hold something that is not arithmetic.
"""

import os
import uuid

import pytest

from apps.billing.db import truncate_all as billing_truncate
from apps.control.db import truncate_all as control_truncate
from apps.ledger.db import truncate_all as ledger_truncate
from oracle.invariants import Verdict

pytestmark = pytest.mark.skipif(
    os.environ.get("ACL_RUN_LLM") != "1"
    or not os.environ.get("DEEPSEEK_API_KEY"),
    reason="live model arms; set ACL_RUN_LLM=1 with a key to run",
)

RUNS = int(os.environ.get("ACL_LLM_RUNS", "3"))


def _run(stack, with_reservation):
    from agents.llm.model import DeepSeek
    from schedules.llm_arms import run_arm

    outcomes = []
    for _ in range(RUNS):
        billing_truncate()
        ledger_truncate()
        control_truncate()
        outcomes.append(
            run_arm(stack, f"llm-{uuid.uuid4().hex[:8]}", DeepSeek(), with_reservation)
        )
    return outcomes


@pytest.fixture(scope="module")
def arm_c(llm_stack):
    return _run(llm_stack, with_reservation=False)


@pytest.fixture(scope="module")
def arm_d(llm_stack):
    return _run(llm_stack, with_reservation=True)


def test_arm_c_reproduces_the_violation_with_a_real_model(arm_c):
    """The finding is not an artifact of a deterministic agent."""
    violations = [r for r in arm_c if r.verdict is Verdict.VIOLATION]

    assert violations, (
        "no run breached the ceiling; the finding did not reproduce under a "
        f"model: {[(r.verdict.value, str(r.committed_total)) for r in arm_c]}"
    )


def test_arm_c_agents_read_before_acting(arm_c):
    """Diligence, not carelessness.

    If the model acted without reading, arm C would only show that an
    ill-behaved agent misbehaves, which is not interesting. It read first and
    was wrong anyway -- the same sentence as the deterministic arm.
    """
    for run in arm_c:
        for transcript in run.transcripts:
            if transcript.acted:
                assert "read_compensation" in transcript.tool_names


def test_arm_d_never_breaches_the_ceiling(arm_d):
    """The claim worth having: the fix is cognition-independent."""
    breaches = [r for r in arm_d if r.verdict is Verdict.VIOLATION]

    assert not breaches, (
        "the coordination authority failed to hold a model: "
        f"{[(r.verdict.value, str(r.committed_total)) for r in breaches]}"
    )


def test_arm_d_refusals_come_from_the_control_not_the_harness(arm_d):
    """Otherwise arm D would be measuring my scaffolding.

    The harness does refuse an issue that was never reserved -- standing in for
    a service that would require one -- so the result only means something if
    the CONTROL SERVICE is what actually refused.
    """
    refused = [t for r in arm_d for t in r.transcripts if t.refused_by_control]

    assert refused, (
        "no run recorded a refusal from the control service; arm D's cleanliness "
        "cannot be attributed to the control"
    )


def test_no_arm_errored(arm_c, arm_d):
    """An exception must not be read as a decline."""
    errors = [e for r in (*arm_c, *arm_d) for e in r.errors]

    assert not errors, f"agents errored rather than deciding: {errors}"
