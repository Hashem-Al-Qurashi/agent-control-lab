"""Live coordinator fixture.

The coordinator's /await genuinely blocks, so it is exercised against a real
uvicorn server on a real socket rather than an in-process ASGI transport. A
transport that quietly serialises requests would make every concurrency test
pass for the wrong reason -- the same class of false negative as a single-worker
service.
"""

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from apps.coordinator.main import app as coordinator_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def coordinator_url():
    port = _free_port()
    config = uvicorn.Config(
        coordinator_app, host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{url}/waiters", timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:  # pragma: no cover - only on a broken environment
        raise RuntimeError("coordinator did not start")

    yield url

    server.should_exit = True
    thread.join(timeout=10.0)


@pytest.fixture()
def clean_coordinator(coordinator_url):
    httpx.post(f"{coordinator_url}/reset", timeout=5.0)
    yield coordinator_url
    httpx.post(f"{coordinator_url}/reset", timeout=5.0)
