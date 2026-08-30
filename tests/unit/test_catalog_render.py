"""The committed catalogue must match the source it claims to be generated from.

Same guarantee as RESULTS.md. A generated document that can be hand-edited is
just a document, and it starts drifting the day someone fixes a typo in it
instead of in the source.
"""

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
RENDERED = REPO / "docs" / "FAILURE-CATALOG.md"


def test_the_committed_markdown_matches_the_yaml():
    from catalog.render import render

    assert RENDERED.read_text() == render(), (
        "docs/FAILURE-CATALOG.md is out of date with catalog/failures.yaml. "
        "Run `make catalog`."
    )


def test_the_rendered_page_says_it_is_generated():
    """A reader who edits it by hand should be told not to, in the file itself."""
    assert "GENERATED" in RENDERED.read_text()[:400]


def test_every_entry_reaches_the_page():
    import yaml

    entries = yaml.safe_load((REPO / "catalog" / "failures.yaml").read_text())["failures"]
    page = RENDERED.read_text()
    missing = [e["id"] for e in entries if e["id"] not in page]

    assert not missing, f"entries absent from the rendered page: {missing}"
