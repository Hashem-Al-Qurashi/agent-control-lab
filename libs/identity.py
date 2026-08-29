"""Signed agent identity.

The claim this supports is precise: the failure occurred DESPITE every action
being properly authenticated. That sentence is only available if identity is
real -- if the agent merely asserted who it was, a reviewer would rightly say
the system had no authentication to speak of.

So identity is a signed token the agent receives and cannot forge or widen. It
carries the actor, its tenant, and its scopes.

Substitution recorded in docs/adr/005-identity-and-policy.md: this provides the
PROPERTY an OIDC provider would (unforgeable, externally-issued, scoped
identity) without running one. What it does not provide is the operational
surface of a real provider -- token lifetimes, key rotation, discovery, refresh.
Those matter for a production system and do not affect what this experiment
measures.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import jwt

ALGORITHM = "HS256"


def _secret() -> str:
    """Read at call time. Local-only, and never the thing under test."""
    return os.environ.get("ACL_TOKEN_SECRET", "agent-control-lab-local-only")


class InvalidToken(Exception):
    """Forged, tampered, or signed with the wrong key.

    Raised rather than degraded to an anonymous identity: an unauthenticated
    caller that silently becomes 'someone' is exactly how authorization gets
    bypassed without anyone noticing.
    """


@dataclass(frozen=True)
class ActorClaims:
    actor_id: str
    tenant: str
    scopes: tuple[str, ...]


def issue_token(actor_id: str, scopes: list[str], tenant: str) -> str:
    return jwt.encode(
        {"sub": actor_id, "tenant": tenant, "scopes": list(scopes)},
        _secret(),
        algorithm=ALGORITHM,
    )


def actor_claims(token: str) -> ActorClaims:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except Exception as exc:  # jwt raises several distinct types
        raise InvalidToken(str(exc)) from exc
    return ActorClaims(
        actor_id=payload["sub"],
        tenant=payload["tenant"],
        scopes=tuple(payload.get("scopes", [])),
    )
