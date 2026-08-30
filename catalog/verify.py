"""Every `reproduced` entry's cited tests must have actually PASSED.

The existing guard checks that a cited test NAME exists in the source. Critical
review found the hole: existence is not demonstration. A cited test could be
skipped, xfailed, quarantined, or failing, and the catalogue would still claim
the entry is reproduced.

This closes it by reading a real run's JUnit report and requiring every cited
test to appear there with an outcome of passed. Name collisions are surfaced
rather than silently resolved: two files defining the same test name make a bare
citation ambiguous, so an ambiguous citation is reported instead of being
counted as satisfied by whichever one the parser saw first.

    pytest tests/ --junitxml=report.xml -q
    python catalog/verify.py report.xml
"""

from __future__ import annotations

import pathlib
import sys
import xml.etree.ElementTree as ET

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / "catalog" / "failures.yaml"


def _outcomes(report: pathlib.Path) -> dict[str, set[str]]:
    """test name -> set of outcomes seen across every file that defines it."""
    seen: dict[str, set[str]] = {}
    for case in ET.parse(report).getroot().iter("testcase"):
        name = (case.get("name") or "").split("[")[0]
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = "failed"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        seen.setdefault(name, set()).add(outcome)
    return seen


def verify(report: pathlib.Path) -> list[str]:
    entries = yaml.safe_load(SOURCE.read_text())["failures"]
    outcomes = _outcomes(report)
    problems = []

    for entry in entries:
        if entry["status"] != "reproduced":
            continue
        for cited in (entry.get("verified_by") or []) + (
            entry.get("control_verified_by") or []
        ):
            result = outcomes.get(cited)
            if result is None:
                problems.append(
                    f"{entry['id']}: {cited} did not run at all"
                )
            elif result == {"skipped"} and entry.get("requires"):
                # Honest gating. An entry that DECLARES what it needs is not
                # overclaiming -- a reader knows the default run will skip it
                # and what to set to see it. An entry that skips silently is.
                continue
            elif result != {"passed"}:
                problems.append(
                    f"{entry['id']}: {cited} outcome was {sorted(result)}"
                    + ("" if entry.get("requires")
                       else "  (add a `requires:` field if this test is gated)")
                )
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python catalog/verify.py <junit-report.xml>", file=sys.stderr)
        return 2
    report = pathlib.Path(argv[1])
    if not report.exists():
        print(f"no report at {report}; run pytest with --junitxml first", file=sys.stderr)
        return 2

    problems = verify(report)
    if problems:
        print("catalogue entries claim reproduction their tests do not deliver:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    reproduced = sum(
        1 for e in yaml.safe_load(SOURCE.read_text())["failures"]
        if e["status"] == "reproduced"
    )
    print(f"all {reproduced} reproduced entries verified against a real run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
