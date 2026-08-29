"""Stage 1: signed agent identity and deterministic authorization.

The claim this exists to support is specific: the failure occurred DESPITE every
action being properly authenticated and properly authorized. That sentence is
only available if authentication and authorization are real -- if the agent
merely asserted who it was, a reviewer would rightly say the system had no
authorization to speak of.

Two properties, both enforced outside the agent:

  authentication -- identity is a signed token the agent cannot forge or widen
  authorization  -- the decision is made by a policy the agent does not evaluate

The second matters most. An LLM that decides its own permissions has no
permissions. The service asks the policy; the agent never does.
"""

import os
from decimal import Decimal

import jwt
import pytest

from libs.identity import (
    InvalidToken,
    actor_claims,
    issue_token,
)
from libs.policy import Decision, evaluate_action


def test_a_token_round_trips_its_claims():
    token = issue_token("A", scopes=["refund:create"], tenant="acme")
    claims = actor_claims(token)

    assert claims.actor_id == "A"
    assert claims.tenant == "acme"
    assert "refund:create" in claims.scopes


def test_a_tampered_token_is_rejected():
    """The agent must not be able to widen its own authority."""
    token = issue_token("A", scopes=["refund:create"], tenant="acme")
    forged = token[:-4] + "AAAA"

    with pytest.raises(InvalidToken):
        actor_claims(forged)


def test_a_token_signed_with_another_key_is_rejected():
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"sub": "A", "scopes": ["refund:create", "refund:unlimited"],
         "tenant": "acme"},
        "not-the-real-key", algorithm="HS256",
    )
    with pytest.raises(InvalidToken):
        actor_claims(forged)


def test_missing_scope_is_denied():
    claims = actor_claims(issue_token("A", scopes=["invoice:read"], tenant="acme"))

    decision = evaluate_action(
        claims, action="refund", amount=Decimal("100.00"), tenant="acme"
    )

    assert decision.outcome is Decision.DENY
    assert "scope" in decision.reason.lower()


def test_cross_tenant_action_is_always_denied():
    """A hard invariant, not a percentage. One breach is a breach."""
    claims = actor_claims(issue_token("A", scopes=["refund:create"], tenant="acme"))

    decision = evaluate_action(
        claims, action="refund", amount=Decimal("1.00"), tenant="other-corp"
    )

    assert decision.outcome is Decision.DENY
    assert "tenant" in decision.reason.lower()


def test_amount_within_authority_is_allowed():
    claims = actor_claims(issue_token("A", scopes=["refund:create"], tenant="acme"))

    decision = evaluate_action(
        claims, action="refund", amount=Decimal("500.00"), tenant="acme"
    )

    assert decision.outcome is Decision.ALLOW


def test_amount_above_threshold_requires_approval():
    claims = actor_claims(issue_token("A", scopes=["refund:create"], tenant="acme"))

    decision = evaluate_action(
        claims, action="refund", amount=Decimal("500.01"), tenant="acme"
    )

    assert decision.outcome is Decision.REQUIRE_APPROVAL


def test_approval_grants_the_higher_amount():
    claims = actor_claims(
        issue_token("A", scopes=["refund:create", "refund:approved"], tenant="acme")
    )

    decision = evaluate_action(
        claims, action="refund", amount=Decimal("900.00"), tenant="acme"
    )

    assert decision.outcome is Decision.ALLOW


def test_the_policy_is_deterministic():
    """Same inputs, same decision, every time. A policy that varies is not a
    control -- and this whole harness depends on controls being controls."""
    claims = actor_claims(issue_token("A", scopes=["refund:create"], tenant="acme"))
    decisions = {
        evaluate_action(claims, action="refund", amount=Decimal("600.00"),
                        tenant="acme").outcome
        for _ in range(50)
    }
    assert len(decisions) == 1


def test_policy_does_not_know_about_the_aggregate_ceiling():
    """The boundary, again.

    Per-action authorization is not aggregate correctness. A policy that also
    enforced the ceiling would be the solution under test, and every finding
    would become circular.
    """
    claims = actor_claims(issue_token("A", scopes=["refund:create"], tenant="acme"))

    # 500 is individually authorised regardless of what already exists elsewhere.
    assert evaluate_action(
        claims, action="refund", amount=Decimal("500.00"), tenant="acme"
    ).outcome is Decision.ALLOW

    # Check the LOGIC, not the prose. The module's docstring necessarily
    # discusses the aggregate in order to explain why the code must not touch
    # it; an earlier version of this test failed on its own explanation.
    import ast
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[2]
    tree = ast.parse((repo / "libs" / "policy.py").read_text())

    class StripDocstrings(ast.NodeTransformer):
        def _strip(self, node):
            self.generic_visit(node)
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
            return node

        visit_Module = _strip
        visit_FunctionDef = _strip
        visit_ClassDef = _strip

    code = ast.unparse(StripDocstrings().visit(tree)).lower()
    for forbidden in ("authorized_compensation", "aggregate", "ceiling"):
        assert forbidden not in code, (
            f"policy LOGIC references {forbidden!r} -- per-action authorization "
            "must not know about the aggregate, or the finding becomes circular"
        )


# --- token lifetime ------------------------------------------------------
#
# ADR-005 substituted signed tokens for an OIDC provider and recorded token
# lifetime as the operational surface it did not provide. That left T1 with a
# real residual -- a leaked token valid forever -- and readiness domain 3 with
# an honest "absent". These close it.


def test_a_token_carries_an_expiry():
    """An immortal credential is one leak away from permanent access."""
    claims = jwt.decode(
        issue_token("A", ["refund:create"], tenant="t1"),
        os.environ.get("ACL_TOKEN_SECRET", "agent-control-lab-local-only"),
        algorithms=["HS256"],
    )

    assert "exp" in claims and "iat" in claims


def test_an_expired_token_is_rejected():
    token = issue_token("A", ["refund:create"], tenant="t1", ttl_seconds=-1)

    with pytest.raises(InvalidToken):
        actor_claims(token)


def test_a_token_without_an_expiry_is_rejected():
    """Fail closed on a credential that predates the requirement.

    Verifying `exp` only when present means a token minted without one is
    accepted forever -- the check would pass by not applying.
    """
    immortal = jwt.encode(
        {"sub": "A", "tenant": "t1", "scopes": []},
        os.environ.get("ACL_TOKEN_SECRET", "agent-control-lab-local-only"),
        algorithm="HS256",
    )

    with pytest.raises(InvalidToken):
        actor_claims(immortal)


def test_a_token_still_inside_its_lifetime_is_accepted():
    claims = actor_claims(issue_token("A", ["refund:create"], tenant="t1", ttl_seconds=60))

    assert claims.actor_id == "A"
