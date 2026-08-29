"""Stage 2: the agent releases a hold whose action did not land.

Reserving is only safe if un-reserving is guaranteed on the paths where the
effect never happens. Otherwise the hardened arm trades one failure for another:
instead of over-spending, the system under-spends invisibly, refusing legitimate
actions against budget that nothing occupies.

That second failure is worse in one respect -- it looks exactly like the control
working correctly, so nobody goes looking.
"""

from decimal import Decimal

import pytest

from agents.diligent.policy import CaseConfig, Clients, run_case

CEILING = Decimal("1000.00")


class FakeService:
    def __init__(self, committed=Decimal("0.00"), fail=False):
        self._committed = committed
        self._fail = fail
        self.creates = []

    def total_committed(self, case_id):
        return self._committed

    def create(self, case_id, amount, idempotency_key):
        if self._fail:
            raise RuntimeError("service unavailable")
        self.creates.append((case_id, amount, idempotency_key))
        return {"id": 1, "state": "COMMITTED"}


class FakeControl:
    def __init__(self, granted=True):
        self._granted = granted
        self.reserved = []
        self.released = []
        self.committed = []
        self._next_id = 1

    def reserve(self, case_id, amount, key, authorized):
        if not self._granted:
            return None
        rid, self._next_id = self._next_id, self._next_id + 1
        self.reserved.append(rid)
        return rid

    def release(self, reservation_id):
        self.released.append(reservation_id)

    def commit(self, reservation_id):
        self.committed.append(reservation_id)


def _config(amount="600.00"):
    return CaseConfig(
        case_id="c1", actor_id="A", schedule_id="S", action="refund",
        amount=Decimal(amount), idempotency_key="k1",
        authorized_compensation=CEILING,
    )


def _clients(billing, control):
    return Clients(
        billing, FakeService(),
        reserve=control.reserve, release=control.release, commit=control.commit,
    )


def test_a_successful_action_commits_its_hold():
    billing, control = FakeService(), FakeControl()

    run_case("c1", _config(), _clients(billing, control))

    assert billing.creates, "the action should have happened"
    assert control.committed == [1]
    assert control.released == []


def test_a_failed_action_releases_its_hold():
    """The leak this exists to prevent."""
    billing, control = FakeService(fail=True), FakeControl()

    with pytest.raises(RuntimeError):
        run_case("c1", _config(), _clients(billing, control))

    assert control.released == [1], "the hold was not released after the failure"
    assert control.committed == []


def test_a_refused_reservation_reserves_nothing_to_release():
    billing, control = FakeService(), FakeControl(granted=False)

    run_case("c1", _config(), _clients(billing, control))

    assert billing.creates == []
    assert control.released == []
    assert control.committed == []


def test_the_failure_still_propagates_after_releasing():
    """Releasing must not swallow the error. A silent failure here would look
    like a decline, and the run would draw a wrong conclusion."""
    billing, control = FakeService(fail=True), FakeControl()

    with pytest.raises(RuntimeError, match="service unavailable"):
        run_case("c1", _config(), _clients(billing, control))


def test_release_is_skipped_when_no_coordination_authority_exists():
    """The baseline arm has nothing to release, and must not pretend otherwise."""
    billing = FakeService(fail=True)

    with pytest.raises(RuntimeError):
        run_case("c1", _config(), Clients(billing, FakeService()))
