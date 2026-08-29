"""Render the assessment sample to PDF.

A script rather than a one-off command, because the PDF is a client-facing
artifact and a hand-made one drifts from the markdown the moment either is
edited. `make assessment-pdf` regenerates it.

The content is not transformed. Every finding, number and test name in the PDF
is whatever ASSESSMENT-SAMPLE.md says, and that file is covered by
tests/unit/test_docs_integrity.py -- so the PDF inherits the guarantee that its
citations name tests and schedules that exist.
"""

from __future__ import annotations

import pathlib
import sys

import markdown
from weasyprint import HTML

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / "docs" / "ASSESSMENT-SAMPLE.md"
OUTPUT = REPO / "docs" / "WHITESTONE-ASSESSMENT-SAMPLE.pdf"

STYLESHEET = """
@page {
  size: A4;
  margin: 20mm 18mm 18mm 18mm;
  @bottom-left {
    content: "Whitestone Partners — Production Agent Assessment (sample)";
    font-size: 7.5pt; color: #767676;
  }
  @bottom-right { content: counter(page); font-size: 7.5pt; color: #767676; }
}
@page :first { @bottom-left { content: ""; } @bottom-right { content: ""; } }

body { font-family: "DejaVu Serif", Georgia, serif; font-size: 10pt;
       line-height: 1.5; color: #1a1a1a; }
h1 { font-size: 21pt; line-height: 1.2; margin: 0 0 4mm 0;
     border-bottom: 2px solid #1a1a1a; padding-bottom: 3mm; }
h2 { font-size: 13pt; margin: 9mm 0 3mm 0; page-break-after: avoid;
     border-bottom: 1px solid #c8c8c8; padding-bottom: 1.5mm; }
h3 { font-size: 11pt; margin: 6mm 0 2mm 0; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.5pt;
       background: #f2f2f2; padding: 0.4mm 1mm; border-radius: 1.5px; }
pre { background: #f7f7f7; border-left: 2.5px solid #b4b4b4; padding: 3mm;
      font-size: 8.5pt; overflow-wrap: break-word; white-space: pre-wrap;
      page-break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0;
        font-size: 9pt; page-break-inside: avoid; }
th, td { border: 1px solid #c8c8c8; padding: 1.8mm 2.5mm;
         text-align: left; vertical-align: top; }
th { background: #efefef; font-weight: bold; }
blockquote { margin: 3mm 0; padding: 0 0 0 4mm; border-left: 2.5px solid #b4b4b4;
             color: #3c3c3c; }
hr { border: none; border-top: 1px solid #d2d2d2; margin: 6mm 0; }
strong { font-weight: bold; }
"""


def build() -> pathlib.Path:
    body = markdown.markdown(
        SOURCE.read_text(),
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )
    document = (
        "<html><head><meta charset='utf-8'>"
        f"<style>{STYLESHEET}</style></head><body>{body}</body></html>"
    )
    HTML(string=document, base_url=str(REPO)).write_pdf(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path.relative_to(REPO)} ({path.stat().st_size:,} bytes)")
    sys.exit(0)
