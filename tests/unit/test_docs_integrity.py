"""The documents cite real things, enforced.

Prose does not fail. A threat model citing a test that was renamed, or an
assessment citing a schedule that was deleted, stays confidently wrong until a
reader tries to follow it -- and by then the whole document is suspect.

These checks are cheap and they are the only thing standing between "every
control is verified by a test" and "every control was verified by a test at the
time of writing".
"""

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"


def _defined_tests() -> set[str]:
    names = set()
    for path in (REPO / "tests").rglob("test_*.py"):
        names.update(re.findall(r"^def (test_[a-z0-9_]+)", path.read_text(), re.M))
    return names


def _declared_schedules() -> set[str]:
    ids = set()
    for path in (REPO / "schedules").glob("*.yaml"):
        match = re.search(r"^schedule_id:\s*(\S+)", path.read_text(), re.M)
        if match:
            ids.add(match.group(1))
    return ids


def _all_docs() -> list[pathlib.Path]:
    """Every prose file, discovered -- never a hand-maintained list.

    The list used to name three files. Four documents and fourteen ADRs were
    written after it, none of them checked, and the suite stayed green the whole
    time: the enforcement passed because it was not looking. A checker with a
    hardcoded scope silently stops covering the repo the moment the repo grows.
    """
    return sorted(DOCS.rglob("*.md")) + [REPO / "README.md"]


def _doc_ids() -> list[str]:
    return [str(p.relative_to(REPO)) for p in _all_docs()]


@pytest.mark.parametrize("doc", _all_docs(), ids=_doc_ids())
def test_every_cited_test_exists(doc):
    cited = set(re.findall(r"`(test_[a-z0-9_]+)`", doc.read_text()))
    missing = sorted(cited - _defined_tests())

    assert not missing, f"{doc.name} cites tests that do not exist: {missing}"


# P4 is the replay-determinism suite, not a schedule -- it replays the others.
NOT_A_SCHEDULE = {"P4"}


@pytest.mark.parametrize("doc", _all_docs(), ids=_doc_ids())
def test_every_cited_schedule_exists(doc):
    """Match the SHAPE of a schedule id, never an enumeration of known ones.

    An enumerated pattern only catches typos in ids that already exist. A
    citation to `S9` matched nothing, so it was not checked -- the check passed
    by failing to see it, which is the same vacuum as a hardcoded file list.
    """
    cited = set(re.findall(r"`([PS]\d+[A-Z]*)`", doc.read_text()))
    missing = sorted(cited - _declared_schedules() - NOT_A_SCHEDULE)

    assert not missing, f"{doc.name} cites schedules that do not exist: {missing}"


def test_every_adr_referenced_by_a_doc_exists():
    adrs = {p.name for p in (DOCS / "adr").glob("*.md")}
    numbers = {name.split("-")[0] for name in adrs}

    for doc in _all_docs():
        for ref in re.findall(r"ADR-(\d{3})", doc.read_text()):
            assert ref in numbers, f"{doc.name} references ADR-{ref}, which does not exist"


def test_reproduce_commands_name_real_schedules():
    """A README instruction that cannot be run is worse than no instruction."""
    for doc in _all_docs():
        for schedule in re.findall(r"make reproduce SCHEDULE=(\S+)", doc.read_text()):
            assert schedule in _declared_schedules(), (
                f"{doc.name} tells the reader to run SCHEDULE={schedule}, "
                "which does not exist"
            )


def test_results_report_covers_every_declared_schedule():
    """A schedule absent from the report is one nobody is reading the verdict of."""
    generator = (REPO / "tests" / "schedules" / "test_results_report.py").read_text()
    covered = set(re.findall(r'\("(\w+)", Verdict\.', generator))
    missing = sorted(_declared_schedules() - covered)

    assert not missing, f"schedules missing from the results report: {missing}"
