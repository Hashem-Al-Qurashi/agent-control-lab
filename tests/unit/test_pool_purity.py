"""Task 12: agent process pool, and the purity lint that keeps it correct.

Two separate concerns that reinforce each other.

Purity: the agent entrypoint must hold no module-level mutable state and read no
environment at import time. One pre-warmed interpreter serves many cases, so
anything captured at import leaks from one case into the next -- and a leak
between cases in a determinism harness produces a result that cannot be
reproduced or trusted.

Pooling: never fork-per-run. A Python process importing the agent stack costs
seconds; at the volumes later modes need that becomes hours of pure interpreter
startup. Pool size must scale with concurrency, not with run count.
"""

import pathlib

import pytest

from agents.diligent.pool import AgentPool
from agents.diligent.purity import PurityViolation, check_module_purity

REPO = pathlib.Path(__file__).resolve().parents[2]
POLICY = REPO / "agents" / "diligent" / "policy.py"


def test_policy_module_is_pure():
    """The lint that keeps the pool model valid."""
    check_module_purity(POLICY)  # raises PurityViolation if not


def test_lint_rejects_module_level_mutable_state(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("CACHE = {}\n\ndef run_case(c, cfg, cl):\n    CACHE[c] = 1\n")

    with pytest.raises(PurityViolation) as exc:
        check_module_purity(bad)
    assert "CACHE" in str(exc.value)


def test_lint_rejects_import_time_environment_reads(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import os\n\nURL = os.environ['SERVICE_URL']\n")

    with pytest.raises(PurityViolation) as exc:
        check_module_purity(bad)
    assert "environ" in str(exc.value).lower()


def test_lint_allows_constants_and_declarations(tmp_path):
    ok = tmp_path / "ok.py"
    ok.write_text(
        "from dataclasses import dataclass\n"
        "\n"
        "CEILING_NAME = 'authorized_compensation'\n"
        "MAX_ITEMS = 10\n"
        "\n"
        "@dataclass(frozen=True)\n"
        "class Config:\n"
        "    x: int\n"
        "\n"
        "def run_case(c, cfg, cl):\n"
        "    return None\n"
    )
    check_module_purity(ok)


def test_lint_allows_call_time_environment_reads(tmp_path):
    ok = tmp_path / "ok.py"
    ok.write_text(
        "import os\n\ndef run_case(c, cfg, cl):\n    return os.environ.get('X')\n"
    )
    check_module_purity(ok)


def test_pool_reuses_processes_rather_than_forking_per_case():
    """10 cases through a pool of 2 must touch at most 2 interpreters."""
    pool = AgentPool(size=2)
    try:
        pids = {pool.submit_echo_pid() for _ in range(10)}
    finally:
        pool.shutdown()

    assert 1 <= len(pids) <= 2, (
        f"10 cases ran in {len(pids)} processes -- the pool is forking per run, "
        "which at later volumes becomes hours of interpreter startup"
    )


def test_pool_workers_are_not_the_parent_process():
    """Agents must be separate OS processes, not threads in the harness."""
    import os

    pool = AgentPool(size=2)
    try:
        worker_pid = pool.submit_echo_pid()
    finally:
        pool.shutdown()

    assert worker_pid != os.getpid()


def test_pool_shutdown_stops_all_workers():
    pool = AgentPool(size=2)
    pool.submit_echo_pid()
    pool.shutdown()

    assert pool.live_workers() == 0
