"""Client for the checkpoint call a service makes from inside a handler.

Auto-retry is disabled deliberately. A client-side retry on a non-idempotent
endpoint is indistinguishable from two agents racing, and would manufacture a
false-positive violation in exactly the experiment this harness exists to run.

The client never invents an actor id. If no identity is bound it raises, because
guessing would fabricate the schedule rather than fail.
"""

from __future__ import annotations

import httpx

from libs.barrier.middleware import outbound_headers


class CheckpointError(Exception):
    """The coordinator refused the checkpoint -- aborted, undeclared, or timed out."""


class BarrierClient:
    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout,
            # retries=0 is httpx's default; stated explicitly because a silent
            # retry here would corrupt the experiment rather than just the test.
            transport=httpx.HTTPTransport(retries=0),
        )

    def checkpoint(self, name: str) -> int:
        """Block until the coordinator releases this actor at this checkpoint."""
        headers = outbound_headers()  # raises MissingActorIdentity if unbound
        response = self._client.post(
            f"{self._base}/await", json={"checkpoint": name}, headers=headers
        )
        if response.status_code != 200:
            raise CheckpointError(
                f"checkpoint {name!r} refused ({response.status_code}): "
                f"{response.text}"
            )
        return response.json()["occurrence"]

    def heartbeat(self, name: str, occurrence: int) -> bool:
        headers = outbound_headers()
        response = self._client.post(
            f"{self._base}/heartbeat",
            json={"checkpoint": name, "occurrence": occurrence},
            headers=headers,
        )
        return bool(response.json().get("refreshed"))

    def close(self) -> None:
        self._client.close()
