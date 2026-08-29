"""Task 10: rig topology assertions.

Each of these guards a specific way the whole experiment becomes an artifact
rather than a finding:

  * shared database  -> there IS a common transaction boundary, so the premise
                        is false and any "violation" is meaningless
  * single worker    -> two agent processes serialise at the request queue,
                        P2 silently equals P1, and that reads as the thesis
                        being falsified
  * SERIALIZABLE +   -> Postgres hands you a lock you never scripted, masking a
    driver retry        real violation

The worker assertion deliberately does not read configuration. It proves
requests were served by distinct OS processes, because a config value that says
4 while something else forces serialisation would pass a config check and still
destroy the result.
"""

import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from apps.billing.db import DEFAULT_DSN as BILLING_DSN
from apps.billing.db import run_migrations as billing_migrations
from apps.ledger.db import DEFAULT_DSN as LEDGER_DSN
from apps.ledger.db import run_migrations as ledger_migrations
from oracle.manifest import build_manifest, dsn_parts

REPO = pathlib.Path(__file__).resolve().parents[2]
HEADERS = {"X-Actor-Id": "A", "X-Schedule-Id": "P1"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def billing_server():
    """A real multi-worker uvicorn, not an in-process test client."""
    port = _free_port()
    env = {**os.environ, "BARRIER_ENABLED": "0", "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "apps.billing.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--workers", "4",
            "--log-level", "error",
        ],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 40.0
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{url}/health", headers=HEADERS, timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:  # pragma: no cover
        proc.send_signal(signal.SIGTERM)
        pytest.fail("billing did not start")

    yield url

    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=15)


def test_billing_and_ledger_use_different_hosts_and_database_names():
    """One config typo pointing both at one database invalidates every result."""
    billing, ledger = dsn_parts(BILLING_DSN), dsn_parts(LEDGER_DSN)

    assert billing["dbname"] != ledger["dbname"], "services share a database name"
    assert (billing["host"], billing["port"]) != (
        ledger["host"],
        ledger["port"],
    ), "services share a database host:port"


def test_requests_are_served_by_multiple_worker_processes(billing_server):
    """Proves genuine concurrency at the server, not a configured intention.

    A single-worker server serialises two agent processes at the request queue.
    P2 would then equal P1 and be misread as the thesis being false.
    """
    def hit(_):
        return httpx.get(
            f"{billing_server}/health", headers=HEADERS, timeout=10.0
        ).json()["pid"]

    with ThreadPoolExecutor(max_workers=12) as pool:
        pids = set(pool.map(hit, range(40)))

    assert len(pids) > 1, (
        f"all {40} requests were served by one process ({pids}) -- the server is "
        "effectively single-worker and concurrency tests would pass for the "
        "wrong reason"
    )


def test_manifest_records_isolation_level_and_retry_behaviour():
    billing_migrations()
    ledger_migrations()
    manifest = build_manifest()

    for service in ("billing", "ledger"):
        entry = manifest["databases"][service]
        assert entry["isolation_level"], f"{service} isolation level not recorded"
        assert "driver_retries_on_serialization_failure" in entry
        assert entry["dbname"] == service


def test_manifest_is_json_serialisable_and_written_to_disk(tmp_path):
    """The manifest is evidence. It has to survive the run that produced it."""
    manifest = build_manifest()
    out = tmp_path / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2))

    reloaded = json.loads(out.read_text())
    assert reloaded["databases"]["billing"]["dbname"] == "billing"
    assert reloaded["git_sha"]


def test_manifest_flags_a_shared_database_as_invalid():
    """The check must fail loudly if the two DSNs ever converge."""
    manifest = build_manifest(
        billing_dsn=BILLING_DSN, ledger_dsn=BILLING_DSN
    )
    assert manifest["topology_valid"] is False
    assert "share" in manifest["topology_error"].lower()
