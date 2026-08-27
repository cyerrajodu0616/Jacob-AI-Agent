"""PDF chunking for knowledge ingestion.

Heading-aware chunker that works on any prose PDF using only its own extracted
text: it splits on detected heading lines, keeps each section together, and
further splits oversized sections at ~`target` chars with a small overlap. Page
numbers are retained for citations.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

Chunk = dict[str, Any]

_HEADING_MAX = 70


def _looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not (3 <= len(s) <= _HEADING_MAX):
        return False
    if s[-1] in ".:,;)":            # body sentences / list tails end this way
        return False
    if s[0] in "-•*0123456789":     # bullets / numbered items
        return False
    return s.count(". ") == 0       # a heading is not a multi-sentence run


def _split_long_at(text: str, target: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= target:
        return [text] if text else []
    parts, start = [], 0
    while start < len(text):
        end = min(start + target, len(text))
        if end < len(text):
            cut = text.rfind(". ", start, end)
            if cut <= start:
                cut = text.rfind(" ", start, end)
            if cut > start:
                end = cut + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [p for p in parts if p]


def generic_pdf_chunks(path: Path, target: int = 1400, overlap: int = 150) -> tuple[str, list[Chunk]]:
    """Chunk a prose PDF by heading. Returns (doc_title, chunks).

    doc_title is the first detected heading, else the filename.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    doc_title = path.stem.replace("-", " ").strip()
    chunks: list[Chunk] = []
    heading = "Overview"
    buf, buf_pages = "", set()
    seen_first_heading = False

    def flush() -> None:
        nonlocal buf, buf_pages
        body = " ".join(buf.split())
        for piece in _split_long_at(body, target, overlap):
            chunks.append({
                "title": doc_title, "heading": heading, "chunk_no": len(chunks),
                "text": piece, "metadata": {"pages": sorted(buf_pages)},
            })
        buf, buf_pages = "", set()

    for page_no, page in enumerate(reader.pages, start=1):
        for raw in (page.extract_text() or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if _looks_like_heading(line):
                if not seen_first_heading:
                    doc_title, seen_first_heading = line, True
                    heading = "Overview"
                    continue
                flush()
                heading = line
            else:
                buf = f"{buf} {line}" if buf else line
                buf_pages.add(page_no)
                if len(buf) >= target * 2:  # runaway section without headings
                    flush()
    flush()
    return doc_title, chunks
