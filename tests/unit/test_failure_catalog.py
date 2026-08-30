"""The failure catalogue must not be able to lie about its own coverage.

A catalogue is only a product if a stranger can run its entries. The failure
mode this file exists to prevent is the one that would destroy the artifact's
credibility in a single reading: an entry marked `reproduced` that nothing
reproduces.

Entries live in catalog/failures.yaml. docs/FAILURE-CATALOG.md is generated from
it and must never be hand-edited -- prose that can drift from the code is the
defect this repo keeps finding in itself.
"""

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = REPO / "catalog" / "failures.yaml"

STATUSES = {"reproduced", "documented", "described"}
CLASSES = {"local", "cross-service", "eventual", "hard", "bounded-time"}
REQUIRED = {
    "id", "name", "family", "invariant_class", "symptom", "mechanism",
    "status", "monitoring_shows", "control",
}


def _entries() -> list[dict]:
    return yaml.safe_load(CATALOG.read_text())["failures"]


def test_the_catalogue_parses_and_is_not_empty():
    assert len(_entries()) >= 10


@pytest.mark.parametrize("field", sorted(REQUIRED))
def test_every_entry_carries_every_required_field(field):
    missing = [e.get("id", "<no id>") for e in _entries() if not e.get(field)]

    assert not missing, f"entries missing {field!r}: {missing}"


def test_ids_are_unique():
    ids = [e["id"] for e in _entries()]

    assert len(ids) == len(set(ids)), "duplicate ids in the catalogue"


def test_ids_follow_the_citable_format():
    """Stable ids are the point -- someone should be able to say 'we're exposed
    to ACL-F07' and have that mean something a year from now."""
    bad = [e["id"] for e in _entries() if not re.fullmatch(r"ACL-F\d{2}", e["id"])]

    assert not bad, f"ids not of the form ACL-Fnn: {bad}"


def test_status_values_are_from_the_allowed_set():
    bad = [(e["id"], e["status"]) for e in _entries() if e["status"] not in STATUSES]

    assert not bad, f"unknown status values: {bad}"


def test_every_invariant_class_is_from_the_taxonomy():
    bad = [
        (e["id"], e["invariant_class"])
        for e in _entries()
        if e["invariant_class"] not in CLASSES
    ]

    assert not bad, f"classes outside INVARIANT-CATALOG's taxonomy: {bad}"


def test_every_reproduced_entry_names_a_test_that_exists(defined_tests):
    """The assertion the whole catalogue rests on.

    An entry claiming `reproduced` with no runnable test is worse than an entry
    that honestly says `described` -- it is the one a reader would catch.
    """
    problems = []
    for e in _entries():
        if e["status"] != "reproduced":
            continue
        cited = e.get("verified_by") or []
        if not cited:
            problems.append(f"{e['id']} claims reproduced with no verified_by")
            continue
        missing = sorted(set(cited) - defined_tests)
        if missing:
            problems.append(f"{e['id']} cites tests that do not exist: {missing}")

    assert not problems, "\n".join(problems)


def test_every_named_control_test_exists(defined_tests):
    """A control nobody verified is a recommendation, not a finding."""
    problems = []
    for e in _entries():
        missing = sorted(set(e.get("control_verified_by") or []) - defined_tests)
        if missing:
            problems.append(f"{e['id']} control cites missing tests: {missing}")

    assert not problems, "\n".join(problems)


def test_every_cited_schedule_exists(declared_schedules):
    problems = []
    for e in _entries():
        missing = sorted(set(e.get("schedules") or []) - declared_schedules)
        if missing:
            problems.append(f"{e['id']} cites schedules that do not exist: {missing}")

    assert not problems, "\n".join(problems)


def test_a_reproduced_entry_tells_you_how_to_run_it():
    missing = [
        e["id"] for e in _entries()
        if e["status"] == "reproduced" and not e.get("reproduce")
    ]

    assert not missing, f"reproduced entries with no command: {missing}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "bounded-time is named in the taxonomy and not yet demonstrated: "
        "reservations have no expiry and approvals have no validity window. "
        "Closed by Phase 2; remove this marker then."
    ),
)
def test_all_five_invariant_classes_are_represented():
    """The taxonomy in INVARIANT-CATALOG.md claims five classes.

    Demonstrating four of them is precisely the gap this build exists to close,
    so it is asserted rather than hoped for. strict=True means this starts
    failing the moment the gap closes, which is what forces the marker to be
    removed instead of quietly outliving the problem.
    """
    present = {e["invariant_class"] for e in _entries()}

    assert present == CLASSES, f"classes absent from the catalogue: {sorted(CLASSES - present)}"


# --- the reproduce commands must actually be runnable ---------------------


def _reproduce_commands() -> list[tuple[str, str]]:
    return [(e["id"], e["reproduce"]) for e in _entries() if e.get("reproduce")]


def test_every_reproduce_command_targets_something_real(declared_schedules):
    """A command that cannot run is worse than no command: the reader tries it.

    Two shapes are allowed -- a make target that exists, or a pytest path that
    exists. Anything else is a typo nobody would notice until a demo.
    """
    makefile = (REPO / "Makefile").read_text()
    targets = set(re.findall(r"^([a-z][a-z0-9-]*):", makefile, re.M))

    problems = []
    for entry_id, command in _reproduce_commands():
        if command.startswith("make "):
            target = command.split()[1]
            if target not in targets:
                problems.append(f"{entry_id}: no make target {target!r}")
        elif command.startswith("pytest "):
            for token in command.split():
                if token.startswith("tests/"):
                    path = REPO / token.split("::")[0]
                    if not path.exists():
                        problems.append(f"{entry_id}: no such path {token!r}")
        else:
            problems.append(f"{entry_id}: unrecognised command shape {command!r}")

    assert not problems, "\n".join(problems)


def test_a_schedule_command_names_the_entrys_own_schedule():
    """Guards the copy-paste error: an entry pointing at a different schedule's
    reproduction reads as working and demonstrates the wrong thing."""
    problems = []
    for entry in _entries():
        command = entry.get("reproduce") or ""
        match = re.search(r"SCHEDULE=(\S+)", command)
        if match and match.group(1) not in (entry.get("schedules") or []):
            problems.append(
                f"{entry['id']} reproduces with SCHEDULE={match.group(1)} "
                f"but declares schedules {entry.get('schedules')}"
            )

    assert not problems, "\n".join(problems)


def test_the_lookup_resolves_every_id():
    from catalog.reproduce import command_for

    for entry_id, expected in _reproduce_commands():
        assert command_for(entry_id) == expected


def test_an_unknown_id_is_refused_rather_than_guessed():
    from catalog.reproduce import UnknownFailure, command_for

    with pytest.raises(UnknownFailure):
        command_for("ACL-F99")


def test_the_lookup_cuts_makes_variable_propagation():
    """Otherwise `make reproduce FAILURE=...` recurses until something kills it.

    make exports command-line variables to sub-makes via MAKEFLAGS, so a
    delegated `make reproduce SCHEDULE=S1` saw FAILURE still set and took the
    FAILURE branch again. Found by a 300s timeout, not by reasoning.
    """
    from catalog.reproduce import _child_env

    env = _child_env()
    assert "MAKEFLAGS" not in env
    assert "FAILURE" not in env
