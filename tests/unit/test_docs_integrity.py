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


@pytest.mark.parametrize(
    "doc", ["THREAT-MODEL.md", "ASSESSMENT-SAMPLE.md", "ENGINEER-BRIEF.md"]
)
def test_every_cited_test_exists(doc):
    text = (DOCS / doc).read_text()
    cited = set(re.findall(r"`(test_[a-z0-9_]+)`", text))
    missing = sorted(cited - _defined_tests())

    assert not missing, f"{doc} cites tests that do not exist: {missing}"


@pytest.mark.parametrize("doc", ["THREAT-MODEL.md", "ASSESSMENT-SAMPLE.md"])
def test_every_cited_schedule_exists(doc):
    text = (DOCS / doc).read_text()
    cited = set(re.findall(r"`(P[0-3]|S1C?|S1H|S[3-6])`", text))
    missing = sorted(cited - _declared_schedules())

    assert not missing, f"{doc} cites schedules that do not exist: {missing}"


def test_every_adr_referenced_by_a_doc_exists():
    adrs = {p.name for p in (DOCS / "adr").glob("*.md")}
    numbers = {name.split("-")[0] for name in adrs}

    for doc in DOCS.glob("*.md"):
        for ref in re.findall(r"ADR-(\d{3})", doc.read_text()):
            assert ref in numbers, f"{doc.name} references ADR-{ref}, which does not exist"


def test_reproduce_commands_name_real_schedules():
    """A README instruction that cannot be run is worse than no instruction."""
    for doc in list(DOCS.glob("*.md")) + [REPO / "README.md"]:
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
