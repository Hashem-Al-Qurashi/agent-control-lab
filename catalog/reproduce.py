"""Resolve a failure id to the command that reproduces it.

`make reproduce FAILURE=ACL-F02` is the promise the catalogue makes: a stranger
reads an entry and runs it. That promise is only as good as the mapping, so the
mapping comes from the catalogue itself rather than a second list in the
Makefile that would drift from it.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / "catalog" / "failures.yaml"


class UnknownFailure(Exception):
    """No such id. Raised rather than guessed at.

    A near-miss lookup would run the wrong reproduction and look like it worked,
    which is the one outcome worse than an error.
    """


def _entries() -> list[dict]:
    return yaml.safe_load(SOURCE.read_text())["failures"]


def command_for(failure_id: str) -> str:
    for entry in _entries():
        if entry["id"] == failure_id.upper():
            command = entry.get("reproduce")
            if not command:
                raise UnknownFailure(f"{failure_id} has no reproduction command")
            return command
    known = ", ".join(e["id"] for e in _entries())
    raise UnknownFailure(f"unknown failure {failure_id!r}. Known ids: {known}")


def _child_env() -> dict[str, str]:
    """Environment for the reproduction, with make's variable propagation cut.

    make exports command-line variables to sub-makes through MAKEFLAGS. So
    `make reproduce FAILURE=ACL-F02` running `make reproduce SCHEDULE=S1` had
    FAILURE still set in the child, which took the FAILURE branch again and
    recursed until the timeout killed it.

    Stripping MAKEFLAGS and FAILURE is what makes the delegation terminate.
    """
    env = dict(os.environ)
    env.pop("MAKEFLAGS", None)
    env.pop("FAILURE", None)
    return env


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python catalog/reproduce.py ACL-F02", file=sys.stderr)
        return 2
    try:
        command = command_for(argv[1])
    except UnknownFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"--> {command}\n")
    return subprocess.call(command, shell=True, cwd=REPO, env=_child_env())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
