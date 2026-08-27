"""Ingestion pipeline: source files → chunks → embeddings → Postgres.

Idempotent by checksum: re-running on an unchanged file is a no-op; a changed
file atomically replaces its own chunks (documents row is versioned in place).

Usage (run from the repo root):
    python -m rag.ingest init                                # create schema
    python -m rag.ingest add    --product 511801 <files…>    # ingest pdf/md
    python -m rag.ingest search --product 511801 "query"     # debug hybrid search
    python -m rag.ingest status                              # what the KB holds

Chunking policy:
    md   — split on ## headings; oversize sections split at ~2800 chars with
           300-char overlap. Title/heading kept on every chunk.
    pdf  — text per page (pypdf), paragraphs accumulated to ~2800 chars with
           300-char overlap; page range recorded in metadata for citations.
    json — the 511801 eApp JSON becomes per-field fact cards; the adapter is
           written against the real file's shape (share it), not guessed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import config

from rag import embedder, store   # runtime retrieval layer (parent package)
from . import chunker             # build-time chunker (this package)

CHUNK_CHARS = 2800
OVERLAP_CHARS = 300


# ── chunk builders ───────────────────────────────────────────────────────────
def _split_long(text: str) -> list[str]:
    text = text.strip()
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []
    parts, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):  # break on a space
            space = text.rfind(" ", start, end)
            if space > start:
                end = space
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - OVERLAP_CHARS, start + 1)
    return [p for p in parts if p]


def chunks_from_md(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    m = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
    title = m.group(1).strip() if m else path.stem.replace("-", " ").title()

    out: list[dict] = []

    def add(heading: str, body: str) -> None:
        body = re.sub(r"^>.*$", "", body, flags=re.MULTILINE)  # drop blockquote banners
        for piece in _split_long(body):
            out.append({
                "title": title, "heading": heading, "chunk_no": len(out),
                "text": piece, "metadata": {},
            })

    parts = re.split(r"^##\s+(.+)$", raw, flags=re.MULTILINE)
    add("Overview", re.sub(r"^#\s+.+$", "", parts[0], flags=re.MULTILINE))
    for i in range(1, len(parts), 2):
        add(parts[i].strip(), parts[i + 1] if i + 1 < len(parts) else "")
    return out


# ── commands ─────────────────────────────────────────────────────────────────
def _expand(paths: list[str]) -> list[Path]:
    """Accept files or a directory. A directory ingests its top-level approved
    sources (*.md/*.pdf) — NOT the docs/ subfolder (drafts under review)."""
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for f in sorted(path.iterdir()):
                if f.is_file() and f.suffix.lower() in (".md", ".pdf"):
                    out.append(f)
        else:
            out.append(path)
    return out


def cmd_add(product: str, paths: list[str], force: bool) -> None:
    for path in _expand(paths):
        if not path.exists():
            sys.exit(f"not found: {path}")
        if path.name == "DOC-PLAN.md":
            continue  # planning index, not knowledge
        if path.suffix.lower() == ".md" and "[VERIFY:" in path.read_text(encoding="utf-8", errors="ignore"):
            sys.exit(f"{path.name}: has unresolved [VERIFY:] markers — resolve or remove before ingesting")
        suffix = path.suffix.lower()
        if suffix not in (".md", ".pdf"):
            sys.exit(f"{path.name}: unsupported type {suffix} (pdf, md)")

        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if not force and store.document_checksum(product, path.name) == checksum:
            print(f"unchanged  {path.name}")
            continue

        if suffix == ".pdf":
            title, chunks = chunker.generic_pdf_chunks(path)
        else:
            chunks = chunks_from_md(path)
            title = chunks[0]["title"] if chunks else path.stem

        if not chunks:
            print(f"no text    {path.name} — skipped")
            continue
        vectors = embedder.embed_texts(
            [f"{c['title']} — {c['heading']}\n{c['text']}" for c in chunks]
        )
        n = store.replace_document(
            product=product, source_type=suffix[1:], source_name=path.name,
            version=None, checksum=checksum, chunks=chunks, embeddings=vectors,
            title=title,
        )
        print(f"ingested   {path.name}: {n} chunks ({title})")


def cmd_search(product: str, query: str, k: int) -> None:
    results = store.hybrid_search(query, product=product, k=k)
    print(f"weak={store.is_weak(results)}")
    for r in results:
        sim = f"{r['vec_sim']:.3f}" if r["vec_sim"] is not None else "  —  "
        fts = f"{r['fts_rank']:.3f}" if r["fts_rank"] is not None else "  —  "
        print(f"  rrf={r['rrf']:.4f} sim={sim} fts={fts}  {r['title']} › {r['heading']}")
        print(f"      {r['snippet'][:140]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Jacob knowledge ingestion")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    p_add = sub.add_parser("add")
    p_add.add_argument("--product", default=config.PRODUCT)
    p_add.add_argument("--force", action="store_true")
    p_add.add_argument("files", nargs="+")
    p_search = sub.add_parser("search")
    p_search.add_argument("--product", default=config.PRODUCT)
    p_search.add_argument("--k", type=int, default=config.SEARCH_TOP_K)
    p_search.add_argument("query")
    p_rm = sub.add_parser("remove")
    p_rm.add_argument("--product", default=config.PRODUCT)
    p_rm.add_argument("source_names", nargs="+")
    sub.add_parser("status")

    args = ap.parse_args()
    if args.cmd == "init":
        from . import migrate
        migrate.main()
    elif args.cmd == "add":
        cmd_add(args.product, args.files, args.force)
    elif args.cmd == "search":
        cmd_search(args.product, args.query, args.k)
    elif args.cmd == "remove":
        for name in args.source_names:
            n = store.remove_document(args.product, name)
            print(f"removed    {name}" if n else f"not found  {name}")
    elif args.cmd == "status":
        print(json.dumps(store.status(), indent=2))


if __name__ == "__main__":
    main()
