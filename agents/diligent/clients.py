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
    def __init__(
        self,
        base_url: str,
        collection: str,
        timeout: float = 60.0,
        token: str | None = None,
        tenant: str | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._collection = collection
        # Carried on every call so the service can authenticate and authorize.
        # Without it the Stage 1 claim -- the failure occurred DESPITE proper
        # authorization -- would rest on unit tests rather than on the runs.
        self._token = token
        self._tenant = tenant
        self._client = httpx.Client(
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=0),
        )

    def _headers(self) -> dict[str, str]:
        headers = dict(outbound_headers())
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._tenant:
            headers["X-Tenant-Id"] = self._tenant
        return headers

    def total_committed(self, case_id: str) -> Decimal:
        response = self._client.get(
            f"{self._base}/{self._collection}",
            params={"case_id": case_id},
            headers=self._headers(),
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
            headers=self._headers(),
        )
        if response.status_code not in (200, 201):
            raise ServiceCallFailed(
                f"create {self._collection} failed ({response.status_code}): "
                f"{response.text}"
            )
        return response.json()

    def close(self) -> None:
        self._client.close()


class ReservationClient:
    """Client for the coordination authority.

    A refusal is a normal outcome, not an error: it means the aggregate would
    have been breached and the agent should decline. Only transport failures
    raise.
    """

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout, transport=httpx.HTTPTransport(retries=0)
        )

    def reserve(
        self, case_id: str, amount, idempotency_key: str, authorized
    ) -> int | None:
        response = self._client.post(
            f"{self._base}/reservations",
            json={
                "case_id": case_id,
                "amount": str(amount),
                "idempotency_key": idempotency_key,
                "authorized_compensation": str(authorized),
            },
            headers=outbound_headers(),
        )
        if response.status_code == 409:
            return None  # refused: the aggregate would be breached
        if response.status_code not in (200, 201):
            raise ServiceCallFailed(
                f"reservation failed ({response.status_code}): {response.text}"
            )
        return response.json()["id"]

    def release(self, reservation_id: int) -> None:
        """Free a hold whose action did not land."""
        self._client.post(
            f"{self._base}/reservations/{reservation_id}/release",
            headers=outbound_headers(),
        )

    def commit(self, reservation_id: int) -> None:
        """Mark a hold as spent."""
        self._client.post(
            f"{self._base}/reservations/{reservation_id}/commit",
            headers=outbound_headers(),
        )

    def close(self) -> None:
        self._client.close()
