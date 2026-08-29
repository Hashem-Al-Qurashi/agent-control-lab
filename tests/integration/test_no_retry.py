"""Task 11 (cont): one decision must produce exactly one request.

A resend on a non-idempotent endpoint is indistinguishable from two agents
racing. It would create a second economic effect from one logical decision and
the oracle would report a violation that never happened.

What this actually guards, and what it does not:

  httpx's `retries` parameter covers CONNECTION ESTABLISHMENT only. Measured
  directly: with retries=5, a 500 response produced 1 request, and a connection
  closed after the request was sent produced 1 request. A connect-level retry
  cannot duplicate a side effect, because the request never reached the server.

  So the real risk is an APPLICATION-level retry loop in our own client. That is
  what these tests guard: the lost-ACK case, where the server has already done
  the work and the response never arrives, is exactly where a well-meaning
  `for attempt in range(3)` would silently double the money.

An earlier version of this test asserted the transport setting instead. It
passed with retries=0 AND retries=3, which is to say it asserted nothing.
"""

import socket
import threading
from decimal import Decimal

import pytest

from agents.diligent.clients import HttpServiceClient, ServiceCallFailed
from libs.barrier.middleware import actor_identity


@pytest.fixture()
def lost_ack_server():
    """Accepts the request, does the 'work', then dies without responding.

    This is P3's shape at the transport level: durable effect, no acknowledgement.
    """
    received = {"n": 0}
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    port = sock.getsockname()[1]

    def serve():
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            try:
                conn.recv(65535)
                received["n"] += 1
            finally:
                conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", received
    sock.close()
    thread.join(timeout=5)


def test_lost_ack_produces_exactly_one_request(lost_ack_server):
    """The load-bearing assertion: no resend after the server has the request."""
    url, received = lost_ack_server
    client = HttpServiceClient(url, "refunds", timeout=2.0)

    with actor_identity("A", "P1"):
        with pytest.raises(Exception):
            client.create("case-1", Decimal("600.00"), "k1")

    assert received["n"] == 1, (
        f"{received['n']} requests reached the server for one decision -- a "
        "resend on a non-idempotent endpoint is indistinguishable from two "
        "agents racing and would manufacture a violation"
    )


def test_lost_ack_on_read_produces_exactly_one_request(lost_ack_server):
    url, received = lost_ack_server
    client = HttpServiceClient(url, "refunds", timeout=2.0)

    with actor_identity("A", "P1"):
        with pytest.raises(Exception):
            client.total_committed("case-1")

    assert received["n"] == 1


def test_server_error_surfaces_rather_than_being_swallowed(lost_ack_server):
    """Failure must reach the caller. A swallowed error is a silent wrong result."""
    url, _ = lost_ack_server
    client = HttpServiceClient(url, "refunds", timeout=2.0)

    with actor_identity("A", "P1"):
        with pytest.raises((ServiceCallFailed, Exception)):
            client.create("case-1", Decimal("600.00"), "k1")
