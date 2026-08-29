"""HTTP clients the agent uses to reach Billing and Ledger.

The agent reads through the service APIs -- that is what a real agent has
access to. This is deliberately different from the oracle, which reads the
databases directly: the agent sees what the system shows it, the oracle sees
what is true. The gap between those two views is itself a finding.

Auto-retry is disabled and asserted, never assumed. A client-side retry on a
non-idempotent endpoint is indistinguishable from two agents racing and would
manufacture a false-positive violation.
"""

from __future__ import annotations

from decimal import Decimal

import httpx

from libs.barrier.middleware import outbound_headers


class ServiceCallFailed(Exception):
    """Surfaced rather than retried. The caller decides, not the transport."""


class HttpServiceClient:
    def __init__(self, base_url: str, collection: str, timeout: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._collection = collection
        self._client = httpx.Client(
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=0),
        )

    def total_committed(self, case_id: str) -> Decimal:
        response = self._client.get(
            f"{self._base}/{self._collection}",
            params={"case_id": case_id},
            headers=outbound_headers(),
        )
        if response.status_code != 200:
            raise ServiceCallFailed(
                f"read {self._collection} failed ({response.status_code})"
            )
        return Decimal(response.json()["total_committed"])

    def create(self, case_id: str, amount: Decimal, idempotency_key: str) -> dict:
        response = self._client.post(
            f"{self._base}/{self._collection}",
            json={
                "case_id": case_id,
                "amount": str(amount),
                "idempotency_key": idempotency_key,
            },
            headers=outbound_headers(),
        )
        if response.status_code not in (200, 201):
            raise ServiceCallFailed(
                f"create {self._collection} failed ({response.status_code}): "
                f"{response.text}"
            )
        return response.json()

    def close(self) -> None:
        self._client.close()
