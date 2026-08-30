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
