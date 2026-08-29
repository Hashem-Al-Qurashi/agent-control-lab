"""Service-side policy enforcement.

The enforcement point is the service, deliberately. An actor that evaluates its
own permissions has no permissions -- whether that actor is an LLM or a
deterministic policy. The agent never calls this; the handler does, before any
effect is written.

Enforcement is opt-in configuration (ACL_ENFORCE_POLICY), never a silent
default. Same rule the barrier follows: participation is explicit, so a service
that cannot enforce fails loudly rather than quietly allowing everything.

A denied action must leave nothing behind -- no row, no event. Enforcing before
the transaction opens is what guarantees that, rather than relying on a rollback
that someone might later restructure away.
"""

from __future__ import annotations

import os
from decimal import Decimal

from fastapi import HTTPException

from libs.identity import InvalidToken, actor_claims
from libs.policy import Decision, evaluate_action


def enforcement_enabled() -> bool:
    """Read at call time, never at import."""
    return os.environ.get("ACL_ENFORCE_POLICY", "0") == "1"


def authorize(request, *, action: str, amount: Decimal) -> None:
    """Authenticate the caller and authorize this one action.

    Raises HTTPException. Returns nothing on success -- there is no "partly
    authorized" outcome to hand back.
    """
    if not enforcement_enabled():
        return

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    try:
        claims = actor_claims(header.split(" ", 1)[1])
    except InvalidToken as exc:
        # Never degrade to an anonymous identity. A caller that silently becomes
        # "someone" is how authorization gets bypassed unnoticed.
        raise HTTPException(
            status_code=401, detail=f"invalid token: {exc}"
        ) from exc

    tenant = request.headers.get("x-tenant-id", claims.tenant)
    decision = evaluate_action(claims, action=action, amount=amount, tenant=tenant)

    if decision.outcome is Decision.ALLOW:
        return
    if decision.outcome is Decision.REQUIRE_APPROVAL:
        raise HTTPException(
            status_code=403, detail=f"approval required: {decision.reason}"
        )
    raise HTTPException(status_code=403, detail=decision.reason)
