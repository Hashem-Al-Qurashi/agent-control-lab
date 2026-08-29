"""Task 1: schedule declaration with server-assigned occurrence index.

The coordinator assigns occurrence_index by counting arrivals of
(schedule_id, actor_id, checkpoint_name). Clients send a 3-tuple and hold no
counter state -- critical for P3, where the retry arrives in a fresh request
context in which any client-side counter would reset to 0.
"""

import pytest

from apps.coordinator.schedule import Schedule, UndeclaredOccurrence


def test_second_arrival_at_same_checkpoint_gets_occurrence_1():
    s = Schedule(
        "P3",
        [
            ("A", "billing.after_commit_before_ack"),
            ("A", "billing.after_commit_before_ack"),
        ],
    )
    assert s.arrive("A", "billing.after_commit_before_ack") == (0, True)
    s.advance()
    assert s.arrive("A", "billing.after_commit_before_ack") == (1, True)


def test_undeclared_occurrence_is_rejected():
    s = Schedule("P1", [("A", "billing.after_read_before_decide")])
    s.arrive("A", "billing.after_read_before_decide")
    s.advance()
    with pytest.raises(UndeclaredOccurrence):
        s.arrive("A", "billing.after_read_before_decide")


def test_unknown_actor_is_rejected():
    s = Schedule("P1", [("A", "billing.after_read_before_decide")])
    with pytest.raises(UndeclaredOccurrence):
        s.arrive("B", "billing.after_read_before_decide")


def test_arrival_out_of_declared_order_is_not_next():
    """B arrives first but A's step is at the pointer: B must park."""
    s = Schedule(
        "P2",
        [
            ("A", "billing.after_read_before_decide"),
            ("B", "ledger.after_read_before_decide"),
        ],
    )
    assert s.arrive("B", "ledger.after_read_before_decide") == (0, False)
    assert s.arrive("A", "billing.after_read_before_decide") == (0, True)


def test_pointer_advances_through_declared_steps():
    s = Schedule(
        "P2",
        [
            ("A", "billing.after_read_before_decide"),
            ("B", "ledger.after_read_before_decide"),
        ],
    )
    s.arrive("A", "billing.after_read_before_decide")
    s.advance()
    assert s.arrive("B", "ledger.after_read_before_decide") == (0, True)
    s.advance()
    assert s.is_complete
