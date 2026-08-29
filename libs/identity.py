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
surface of a real provider -- key rotation, discovery, refresh. Those matter for
a production system and do not affect what this experiment measures.

Token lifetime IS enforced: tokens carry `exp`, expired tokens are rejected, and
a token without `exp` is rejected rather than trusted. That bounds the window a
leaked credential is useful for. It does not stop replay INSIDE that window --
there is no jti ledger -- which stays a stated residual in the threat model
rather than a defence this claims to have.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass

import jwt

ALGORITHM = "HS256"

# Long enough that no schedule outlives its own credentials -- the full suite
# runs for minutes, and a token expiring mid-run would surface as a flaky
# authorization failure rather than as the thing it is.
DEFAULT_TTL_SECONDS = 3600


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


def issue_token(
    actor_id: str,
    scopes: list[str],
    tenant: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode(
        {
            "sub": actor_id,
            "tenant": tenant,
            "scopes": list(scopes),
            "iat": now,
            "exp": now + datetime.timedelta(seconds=ttl_seconds),
        },
        _secret(),
        algorithm=ALGORITHM,
    )


def actor_claims(token: str) -> ActorClaims:
    try:
        payload = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],
            # `require` is the load-bearing half. Verifying `exp` only when it
            # is present means a token minted without one is accepted forever,
            # and the check passes by not applying.
            options={"require": ["exp", "iat", "sub"], "verify_exp": True},
        )
    except Exception as exc:  # jwt raises several distinct types
        raise InvalidToken(str(exc)) from exc
    return ActorClaims(
        actor_id=payload["sub"],
        tenant=payload["tenant"],
        scopes=tuple(payload.get("scopes", [])),
    )
