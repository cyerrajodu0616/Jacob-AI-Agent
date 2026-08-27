"""Combine the approved 511801 knowledge docs into one styled PDF.

markdown -> HTML -> PDF via headless Chrome. Reading order is curated (overview
first, screen-by-screen reference last).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import markdown

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "knowledge" / "511801" / "docs"          # markdown sources
OUT_HTML = REPO / "knowledge" / "511801" / "_combined.html"
OUT_PDF = REPO / "knowledge" / "511801" / "NewBridge-Final-Expense-511801-Agent-Guide.pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Curated reading order (files not listed are appended alphabetically after).
ORDER = [
    "product-overview.md",
    "coverage-and-eligibility.md",
    "riders.md",
    "cash-value-and-provisions.md",
    "premiums-and-payment.md",
    "application-process.md",
    "application-screens.md",
]

CSS = """
@page { size: Letter; margin: 22mm 20mm; }
* { box-sizing: border-box; }
body { font-family: Georgia, 'Iowan Old Style', serif; color: #1b2420;
       line-height: 1.55; font-size: 11pt; margin: 0; }
h1 { font-size: 20pt; color: #0e5c54; margin: 0 0 .2em; letter-spacing: -.01em;
     border-bottom: 2px solid #0e7c74; padding-bottom: .25em; }
h2 { font-size: 14pt; color: #14403a; margin: 1.4em 0 .4em; }
h3 { font-size: 12pt; color: #1b2420; margin: 1em 0 .3em; }
p, li { font-size: 11pt; }
ul, ol { margin: .4em 0 .8em; padding-left: 1.4em; }
li { margin: .2em 0; }
code { font-family: 'SF Mono', Menlo, monospace; font-size: .9em;
       background: #eef4f2; padding: 1px 4px; border-radius: 3px; }
strong { color: #14403a; }
.doc { page-break-before: always; }
.doc:first-of-type { page-break-before: avoid; }
/* Cover */
.cover { page-break-after: always; text-align: center; padding-top: 34%; }
.cover .k { font-family: 'SF Mono', Menlo, monospace; font-size: 10pt;
            letter-spacing: .22em; text-transform: uppercase; color: #0e7c74; }
.cover h1 { font-size: 30pt; border: none; color: #14403a; margin: .3em 0; }
.cover .sub { font-size: 13pt; color: #5c6b63; }
.cover .meta { font-family: 'SF Mono', Menlo, monospace; font-size: 9pt;
               color: #8da096; margin-top: 2.5em; }
.toc { page-break-after: always; }
.toc h2 { border-bottom: 1px solid #d6ded9; padding-bottom: .3em; }
.toc ol { font-size: 12pt; line-height: 2; }
"""


def build() -> None:
    files = [DOCS / n for n in ORDER if (DOCS / n).exists()]
    files += sorted(p for p in DOCS.glob("*.md")
                    if p not in files and p.name != "DOC-PLAN.md")
    if not files:
        sys.exit("no .md files found")

    md = markdown.Markdown(extensions=["extra", "sane_lists"])
    sections, toc = [], []
    for i, f in enumerate(files, 1):
        md.reset()
        html = md.convert(f.read_text(encoding="utf-8"))
        # first <h1> text for the TOC
        title = f.stem.replace("-", " ").title()
        if "<h1>" in html:
            title = html.split("<h1>", 1)[1].split("</h1>", 1)[0]
        toc.append(f'<li>{title}</li>')
        sections.append(f'<section class="doc">{html}</section>')

    cover = (
        '<div class="cover">'
        '<div class="k">NewBridge Final Expense · Product 511801</div>'
        '<h1>Agent Knowledge Base</h1>'
        '<div class="sub">Product, coverage, riders, payments, and the application journey</div>'
        '<div class="meta">Continental General · Internal reference for licensed agents · '
        'compiled from approved product documentation</div>'
        '</div>'
    )
    toc_html = f'<div class="toc"><h2>Contents</h2><ol>{"".join(toc)}</ol></div>'
    doc = (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<style>{CSS}</style></head><body>'
        f'{cover}{toc_html}{"".join(sections)}'
        f'</body></html>'
    )
    OUT_HTML.write_text(doc, encoding="utf-8")

    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()],
        check=True, capture_output=True, timeout=120,
    )
    OUT_HTML.unlink(missing_ok=True)
    kb = OUT_PDF.stat().st_size // 1024
    print(f"built {OUT_PDF.name} from {len(files)} docs ({kb} KB)")


if __name__ == "__main__":
    build()
