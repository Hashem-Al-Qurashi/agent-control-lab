"""Render catalog/failures.yaml to docs/FAILURE-CATALOG.md.

Generated rather than written, for the same reason RESULTS.md is: a document
that can be edited independently of its source drifts the first time somebody
fixes a typo in the wrong place, and prose does not fail a test suite.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / "catalog" / "failures.yaml"
OUTPUT = REPO / "docs" / "FAILURE-CATALOG.md"

STATUS_LABEL = {
    "reproduced": "**Reproduced here**",
    "documented": "Documented in the wild",
    "described": "Described, not yet reproduced",
}

HEADER = """# Failure Catalogue

<!-- GENERATED from catalog/failures.yaml by `make catalog`. Do not hand-edit. -->

Named failure modes for action-taking agents. Every entry marked **Reproduced
here** runs on your machine with one command, and a test asserts that claim —
`tests/unit/test_failure_catalog.py` fails if any entry cites a test or schedule
that does not exist.

Status means what it says:

| Status | Meaning |
|---|---|
| **Reproduced here** | A test in this repo produces it on demand |
| Documented in the wild | Observed elsewhere, cited to a primary source read directly |
| Described, not yet reproduced | Named and understood, not demonstrated here |

The third row is why this is usable. A catalogue that admits what it has not
tested is worth more than one that does not distinguish.
"""


def _summary(entries: list[dict]) -> str:
    by_status: dict[str, int] = {}
    by_class: dict[str, int] = {}
    for entry in entries:
        by_status[entry["status"]] = by_status.get(entry["status"], 0) + 1
        by_class[entry["invariant_class"]] = by_class.get(entry["invariant_class"], 0) + 1

    lines = ["\n## Coverage\n", f"**{len(entries)} entries.**\n"]
    lines.append("| Status | Count |")
    lines.append("|---|---:|")
    for status in ("reproduced", "documented", "described"):
        if status in by_status:
            lines.append(f"| {STATUS_LABEL[status]} | {by_status[status]} |")

    lines.append("\n| Invariant class | Count |")
    lines.append("|---|---:|")
    for kind in ("local", "cross-service", "eventual", "hard", "bounded-time"):
        lines.append(f"| `{kind}` | {by_class.get(kind, 0)} |")

    absent = [k for k in ("local", "cross-service", "eventual", "hard", "bounded-time")
              if not by_class.get(k)]
    if absent:
        lines.append(
            f"\n> **Incomplete by its own taxonomy.** `INVARIANT-CATALOG.md` names five "
            f"classes and this catalogue demonstrates {5 - len(absent)}: "
            f"{', '.join('`' + a + '`' for a in absent)} "
            f"{'is' if len(absent) == 1 else 'are'} named and not yet shown breaking. "
            "Stated here rather than left for a reader to notice."
        )
    return "\n".join(lines) + "\n"


def _index(entries: list[dict]) -> str:
    lines = ["\n## Index\n", "| ID | Failure | Class | Status |", "|---|---|---|---|"]
    for e in entries:
        lines.append(
            f"| [`{e['id']}`](#{e['id'].lower()}) | {e['name']} "
            f"| `{e['invariant_class']}` | {STATUS_LABEL[e['status']]} |"
        )
    return "\n".join(lines) + "\n"


def _entry(e: dict) -> str:
    lines = [
        f"\n---\n\n## {e['id']}",
        f"\n### {e['name']}\n",
        f"**Family:** `{e['family']}` · **Invariant class:** `{e['invariant_class']}` "
        f"· **Status:** {STATUS_LABEL[e['status']]}\n",
        f"**Symptom.** {e['symptom'].strip()}\n",
        f"**Mechanism.** {e['mechanism'].strip()}\n",
        f"**What monitoring shows.** {e['monitoring_shows'].strip()}\n",
        f"**Control.** {e['control'].strip()}\n",
    ]
    if e.get("reproduce"):
        lines.append(f"**Reproduce:**\n\n```\n{e['reproduce']}\n```\n")
    if e.get("verified_by"):
        lines.append(
            "**Verified by:** " + ", ".join(f"`{t}`" for t in e["verified_by"]) + "\n"
        )
    if e.get("control_verified_by"):
        lines.append(
            "**Control verified by:** "
            + ", ".join(f"`{t}`" for t in e["control_verified_by"])
            + "\n"
        )
    if e.get("schedules"):
        lines.append("**Schedules:** " + ", ".join(f"`{s}`" for s in e["schedules"]) + "\n")
    if e.get("notes"):
        lines.append(f"**Note.** {e['notes'].strip()}\n")
    return "\n".join(lines)


def render() -> str:
    entries = yaml.safe_load(SOURCE.read_text())["failures"]
    parts = [HEADER, _summary(entries), _index(entries)]
    parts.extend(_entry(e) for e in entries)
    return "".join(parts)


if __name__ == "__main__":
    OUTPUT.write_text(render())
    print(f"wrote {OUTPUT.relative_to(REPO)}")
