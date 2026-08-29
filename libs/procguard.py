"""Which service processes belong to this test session, and which do not.

A killed suite can leave uvicorn workers alive holding connections to the same
databases. They compete for connections and CPU, and timing-sensitive behaviour
diverges -- ADR-007 records a replay divergence that did not reproduce once
orphans were cleared.

Detecting that with a bare `pgrep` does not work, because a suite that spawns
services cannot tell its own processes from a previous run's. Ownership has to
be tracked, and it has to survive `--workers`: uvicorn forks children whose pids
the spawning process never learns, so a claim on the supervisor must extend down
the process tree.
"""

from __future__ import annotations

import subprocess


class ProcessOwnership:
    """Pids this session spawned, and everything descended from them."""

    def __init__(self) -> None:
        self._claimed: set[int] = set()

    def claim(self, pid: int) -> None:
        self._claimed.add(pid)

    def release(self, pid: int) -> None:
        """Stop vouching for a pid once its process is gone.

        Without this a pid the OS later reuses would be trusted on the strength
        of a process that no longer exists.
        """
        self._claimed.discard(pid)

    def foreign(self, pids: list[int], parent_of: dict[int, int]) -> list[int]:
        """The pids not descended from anything this session claimed."""
        return sorted(p for p in pids if not self._owns(p, parent_of))

    def _owns(self, pid: int, parent_of: dict[int, int]) -> bool:
        seen: set[int] = set()
        current = pid
        # Bounded by `seen` rather than by trusting the table to be acyclic: a
        # malformed ps output must fail the check, never hang the suite.
        while current and current not in seen:
            if current in self._claimed:
                return True
            seen.add(current)
            current = parent_of.get(current, 0)
        return False


def parent_map() -> dict[int, int]:
    """pid -> ppid for every live process."""
    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid="], capture_output=True, text=True
    )
    parents: dict[int, int] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            parents[int(fields[0])] = int(fields[1])
    return parents


def running_service_pids() -> list[int]:
    result = subprocess.run(
        ["pgrep", "-f", "uvicorn apps\\."], capture_output=True, text=True
    )
    return [int(p) for p in result.stdout.split() if p]
