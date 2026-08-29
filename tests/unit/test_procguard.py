"""The orphan guard must distinguish 'left by a previous run' from 'mine'.

The guard was a bare `pgrep`. Two session-scoped fixtures in the schedules
suite each spawn services and each call the guard, so whichever built second
saw the first one's live processes and aborted the run calling them orphans.

Fifty-three tests errored in the full suite while every one of them passed in
isolation -- the signature of a guard that is measuring the suite rather than
the environment.
"""

import pytest

from libs.procguard import ProcessOwnership


def test_a_process_this_session_started_is_not_an_orphan():
    own = ProcessOwnership()
    own.claim(100)

    assert own.foreign([100], parent_of={100: 1}) == []


def test_a_process_nobody_claimed_is_an_orphan():
    own = ProcessOwnership()

    assert own.foreign([100], parent_of={100: 1}) == [100]


def test_a_worker_child_of_a_claimed_supervisor_is_not_an_orphan():
    """uvicorn --workers forks children with PIDs the parent never sees.

    Claiming only the Popen pid would flag every worker as an orphan, which is
    the same false alarm in a subtler place.
    """
    own = ProcessOwnership()
    own.claim(100)

    assert own.foreign([100, 101, 102], parent_of={100: 1, 101: 100, 102: 100}) == []


def test_a_grandchild_of_a_claimed_process_is_not_an_orphan():
    own = ProcessOwnership()
    own.claim(100)

    assert own.foreign([200], parent_of={200: 150, 150: 100, 100: 1}) == []


def test_releasing_a_pid_makes_its_children_foreign_again():
    """A torn-down stack must stop vouching for anything.

    Without release, a PID reused by the OS later would be silently trusted.
    """
    own = ProcessOwnership()
    own.claim(100)
    own.release(100)

    assert own.foreign([100, 101], parent_of={100: 1, 101: 100}) == [100, 101]


def test_an_unknown_parent_terminates_the_walk_rather_than_looping():
    own = ProcessOwnership()
    own.claim(999)

    assert own.foreign([100], parent_of={100: 50}) == [100]


def test_a_parent_cycle_does_not_hang():
    """Defensive: a malformed ps table must not spin forever."""
    own = ProcessOwnership()
    own.claim(999)

    assert own.foreign([100], parent_of={100: 101, 101: 100}) == [100]


def test_foreign_pids_are_reported_in_order():
    own = ProcessOwnership()

    assert own.foreign([300, 100, 200], parent_of={}) == [100, 200, 300]
