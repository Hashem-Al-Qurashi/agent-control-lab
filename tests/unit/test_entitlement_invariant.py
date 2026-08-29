"""Stage 5: the same failure shape on a non-monetary invariant.

Everything so far sums money. A reader can reasonably suspect the result is
about arithmetic -- that sums are special, or that Decimal is the interesting
part.

It is not. The structure is: an authority owns a fact, a second system acts on a
derived copy of that fact, and the copy is behind. Whether the fact is a dollar
total or a subscription tier changes nothing.

E1: every granted feature must be permitted by the case's current plan.

No sums. No money. A set-membership rule over two independently-owned systems,
and it breaks exactly the way the compensation ceiling does.
"""

import pytest

from oracle.entitlements import (
    FEATURES_BY_PLAN,
    EntitlementVerdict,
    evaluate_entitlements,
)


def test_a_plan_permits_its_own_features():
    assert "reports" in FEATURES_BY_PLAN["BASIC"]
    assert "sso" in FEATURES_BY_PLAN["PRO"]
    assert "sso" not in FEATURES_BY_PLAN["BASIC"]


def test_grants_within_the_plan_are_clean():
    result = evaluate_entitlements(plan="PRO", granted={"reports", "api", "sso"})

    assert result.verdict is EntitlementVerdict.CLEAN
    assert result.unpermitted == set()


def test_a_grant_outside_the_plan_is_a_violation():
    """The non-monetary analogue of the compensation breach."""
    result = evaluate_entitlements(plan="BASIC", granted={"reports", "sso"})

    assert result.verdict is EntitlementVerdict.VIOLATION
    assert result.unpermitted == {"sso"}


def test_the_violation_names_every_unpermitted_feature():
    """A verdict that says 'something is wrong' is not actionable."""
    result = evaluate_entitlements(plan="BASIC", granted={"api", "sso", "reports"})

    assert result.unpermitted == {"api", "sso"}


def test_fewer_grants_than_the_plan_allows_is_clean():
    """Under-granting is not a breach. The invariant is a ceiling on authority,
    not a requirement to use it."""
    result = evaluate_entitlements(plan="PRO", granted={"reports"})

    assert result.verdict is EntitlementVerdict.CLEAN


def test_no_plan_permits_nothing():
    """Absent a plan, any grant is unpermitted. Failing open here would let a
    missing record authorise everything."""
    result = evaluate_entitlements(plan=None, granted={"reports"})

    assert result.verdict is EntitlementVerdict.VIOLATION
    assert result.unpermitted == {"reports"}


def test_an_unknown_plan_raises_rather_than_permitting():
    """Guessing what an unrecognised plan allows is how authority leaks."""
    with pytest.raises(KeyError):
        evaluate_entitlements(plan="ENTERPRISE_TRIAL", granted={"sso"})
