"""Deterministic schedule: declared step list, pointer, server-assigned occurrence.

A checkpoint cannot derive the actor from the runtime -- PID, thread id, task id
and contextvars all identify the *server's* unit of work, not the caller. Actor
identity arrives as a wire value, and the coordinator computes the occurrence
index itself so that clients hold no counter state.

Barrier key is the 4-tuple (schedule_id, actor_id, checkpoint_name,
occurrence_index). The occurrence index is mandatory: P3's retry hits
`after_commit_before_ack` a second time, and a 3-part key would either consume
the first hit's release token or deadlock.
"""

from __future__ import annotations

from collections import Counter


class UndeclaredOccurrence(Exception):
    """Raised when an arrival does not correspond to a declared step.

    Covers an unknown actor, an unknown checkpoint, and an occurrence beyond the
    number declared. The coordinator fails closed on this: abort the run and dump
    all waiters. A default-releasing barrier manufactures results.
    """


Step = tuple[str, str]


class Schedule:
    def __init__(self, schedule_id: str, steps: list[Step]) -> None:
        self.schedule_id = schedule_id
        self._steps: list[Step] = list(steps)
        self._pointer = 0
        self._arrivals: Counter[Step] = Counter()

        # For each declared step, which occurrence of (actor, checkpoint) it is.
        seen: Counter[Step] = Counter()
        self._step_occurrence: list[int] = []
        for step in self._steps:
            self._step_occurrence.append(seen[step])
            seen[step] += 1

        self._declared: set[tuple[str, str, int]] = {
            (actor, checkpoint, occurrence)
            for (actor, checkpoint), occurrence in zip(
                self._steps, self._step_occurrence
            )
        }

    @property
    def is_complete(self) -> bool:
        return self._pointer >= len(self._steps)

    @property
    def pointer(self) -> int:
        return self._pointer

    @property
    def current_step(self) -> tuple[str, str, int] | None:
        """The 4-tuple key (minus schedule_id) the pointer is waiting on."""
        if self.is_complete:
            return None
        actor, checkpoint = self._steps[self._pointer]
        return actor, checkpoint, self._step_occurrence[self._pointer]

    def arrive(self, actor_id: str, checkpoint: str) -> tuple[int, bool]:
        """Register an arrival. Returns (occurrence_index, is_next).

        is_next is False when the arrival is a declared step that is not yet at
        the pointer -- the waiter parks. Raises UndeclaredOccurrence otherwise.
        """
        step: Step = (actor_id, checkpoint)
        occurrence = self._arrivals[step]

        if (actor_id, checkpoint, occurrence) not in self._declared:
            raise UndeclaredOccurrence(
                f"schedule={self.schedule_id} actor={actor_id} "
                f"checkpoint={checkpoint} occurrence={occurrence} is not declared"
            )

        self._arrivals[step] += 1
        return occurrence, self._matches_pointer(step, occurrence)

    def advance(self) -> None:
        self._pointer += 1

    def _matches_pointer(self, step: Step, occurrence: int) -> bool:
        if self.is_complete:
            return False
        return (
            self._steps[self._pointer] == step
            and self._step_occurrence[self._pointer] == occurrence
        )
