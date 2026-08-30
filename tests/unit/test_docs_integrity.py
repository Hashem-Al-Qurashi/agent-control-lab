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

from conftest import _scan_declared_schedules

REPO = pathlib.Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"


# Scanners live in tests/unit/conftest.py as session fixtures. Two copies of
# "which tests exist" drift, and the copy that drifts is the one that quietly
# stops catching anything.


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
def test_every_cited_test_exists(doc, defined_tests):
    cited = set(re.findall(r"`(test_[a-z0-9_]+)`", doc.read_text()))
    missing = sorted(cited - defined_tests)

    assert not missing, f"{doc.name} cites tests that do not exist: {missing}"


# P4 is the replay-determinism suite, not a schedule -- it replays the others.
NOT_A_SCHEDULE = {"P4"}


@pytest.mark.parametrize("doc", _all_docs(), ids=_doc_ids())
def test_every_cited_schedule_exists(doc, declared_schedules):
    """Match the SHAPE of a schedule id, never an enumeration of known ones.

    An enumerated pattern only catches typos in ids that already exist. A
    citation to `S9` matched nothing, so it was not checked -- the check passed
    by failing to see it, which is the same vacuum as a hardcoded file list.
    """
    cited = set(re.findall(r"`([PS]\d+[A-Z]*)`", doc.read_text()))
    missing = sorted(cited - declared_schedules - NOT_A_SCHEDULE)

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
            assert schedule in _scan_declared_schedules(), (
                f"{doc.name} tells the reader to run SCHEDULE={schedule}, "
                "which does not exist"
            )


def test_results_report_covers_every_declared_schedule():
    """A schedule absent from the report is one nobody is reading the verdict of."""
    generator = (REPO / "tests" / "schedules" / "test_results_report.py").read_text()
    covered = set(re.findall(r'\("(\w+)", Verdict\.', generator))
    missing = sorted(_scan_declared_schedules() - covered)

    assert not missing, f"schedules missing from the results report: {missing}"


def test_the_assessment_pdf_builder_points_at_a_real_source():
    """The client-facing artifact is generated, so its generator must not rot.

    A renamed or moved ASSESSMENT-SAMPLE.md would leave the last-built PDF sitting
    in the repo looking current while `make assessment-pdf` failed -- and a stale
    PDF is worse than a missing one, because it still gets sent.
    """
    from tools.build_assessment_pdf import OUTPUT, SOURCE

    assert SOURCE.exists(), f"the PDF generator reads {SOURCE}, which is gone"
    assert OUTPUT.exists(), "run `make assessment-pdf` -- the built PDF is missing"


def test_the_assessment_pdf_is_not_older_than_its_source():
    """Catches the edit-the-markdown-forget-the-PDF case in a checkout that has
    real mtimes. Skipped where git has flattened them (a fresh clone)."""
    from tools.build_assessment_pdf import OUTPUT, SOURCE

    if abs(OUTPUT.stat().st_mtime - SOURCE.stat().st_mtime) < 2:
        pytest.skip("mtimes are indistinguishable -- likely a fresh checkout")

    assert OUTPUT.stat().st_mtime >= SOURCE.stat().st_mtime, (
        "ASSESSMENT-SAMPLE.md is newer than the PDF built from it; "
        "run `make assessment-pdf`"
    )
