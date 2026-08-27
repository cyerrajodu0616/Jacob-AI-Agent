"""Postgres + pgvector knowledge store: schema, ingestion upserts, and the
hybrid retrieval query.

Retrieval is hybrid by design — every search runs BOTH signals and fuses them:
  - semantic:  pgvector cosine distance over mxbai embeddings (HNSW index)
  - lexical:   Postgres full-text search over title+heading+text (GIN index)
  - fusion:    reciprocal-rank fusion (RRF, k=60)

`is_weak()` is the ground-or-escalate gate: no results, or a best hit that is
both semantically distant and lexically unmatched, means the KB does not cover
the question.
"""
from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.types.json import Json

import config

from . import embedder

_HYBRID_SQL = """
WITH vec AS (
    SELECT id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> %(qv)s::vector) AS r,
           1 - (embedding <=> %(qv)s::vector) AS sim
    FROM jacob.chunks
    WHERE product_id = %(product)s
    ORDER BY embedding <=> %(qv)s::vector
    LIMIT 20
),
fts AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY rank DESC) AS r, rank
    FROM (
        SELECT id, ts_rank_cd(tsv, websearch_to_tsquery('english', %(q)s)) AS rank
        FROM jacob.chunks
        WHERE product_id = %(product)s
          AND tsv @@ websearch_to_tsquery('english', %(q)s)
        ORDER BY rank DESC
        LIMIT 20
    ) t
)
SELECT c.title, c.heading, c.chunk_text, c.metadata, c.chunk_no, c.id,
       d.source_name, d.source_type,
       (COALESCE(1.0 / (60 + vec.r), 0) + COALESCE(1.0 / (60 + fts.r), 0)) AS rrf,
       vec.sim  AS vec_sim,
       fts.rank AS fts_rank
FROM jacob.chunks c
JOIN jacob.documents d ON d.id = c.document_id
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN fts ON fts.id = c.id
WHERE vec.id IS NOT NULL OR fts.id IS NOT NULL
ORDER BY rrf DESC
LIMIT %(k)s;
"""


def connect() -> psycopg.Connection:
    return psycopg.connect(config.DB_DSN)


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def document_checksum(product: str, source_name: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT checksum FROM jacob.documents WHERE product_id=%s AND source_name=%s",
            (product, source_name),
        ).fetchone()
    return row[0] if row else None


def replace_document(
    product: str,
    source_type: str,
    source_name: str,
    version: str | None,
    checksum: str,
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
    title: str | None = None,
) -> int:
    """Atomically (re)ingest one document: upsert the document row, drop its
    old chunks, insert the new set. Returns the chunk count."""
    assert len(chunks) == len(embeddings)
    with connect() as conn:
        conn.execute(
            "INSERT INTO jacob.products (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (product, f"Product {product}"),
        )
        doc_id = conn.execute(
            """
            INSERT INTO jacob.documents (product_id, source_type, source_name, title, version,
                                         checksum, embed_model, embed_dim)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (product_id, source_name) DO UPDATE SET
                source_type = EXCLUDED.source_type,
                title       = EXCLUDED.title,
                version     = EXCLUDED.version,
                checksum    = EXCLUDED.checksum,
                embed_model = EXCLUDED.embed_model,
                embed_dim   = EXCLUDED.embed_dim,
                status      = 'active',
                ingested_at = now()
            RETURNING id
            """,
            (product, source_type, source_name, title, version, checksum,
             config.EMBED_MODEL, config.EMBED_DIM),
        ).fetchone()[0]
        conn.execute("DELETE FROM jacob.chunks WHERE document_id = %s", (doc_id,))
        with conn.cursor() as cur:
            for ch, emb in zip(chunks, embeddings):
                cur.execute(
                    """
                    INSERT INTO jacob.chunks (document_id, product_id, title, heading,
                                              chunk_no, chunk_text, token_est, metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                    """,
                    (doc_id, product, ch["title"], ch.get("heading", ""),
                     ch["chunk_no"], ch["text"], len(ch["text"]) // 4,
                     Json(ch.get("metadata", {})), _vec_literal(emb)),
                )
    return len(chunks)


def remove_document(product: str, source_name: str) -> int:
    """Delete a document and (via cascade) its chunks. Returns rows removed."""
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM jacob.documents WHERE product_id=%s AND source_name=%s",
            (product, source_name),
        )
        return cur.rowcount


_FTS_ONLY_SQL = """
SELECT c.title, c.heading, c.chunk_text, c.metadata, c.chunk_no, c.id,
       d.source_name, d.source_type,
       ts_rank_cd(c.tsv, websearch_to_tsquery('english', %(q)s)) AS rrf,
       NULL::float AS vec_sim,
       ts_rank_cd(c.tsv, websearch_to_tsquery('english', %(q)s)) AS fts_rank
FROM jacob.chunks c
JOIN jacob.documents d ON d.id = c.document_id
WHERE c.product_id = %(product)s
  AND c.tsv @@ websearch_to_tsquery('english', %(q)s)
ORDER BY fts_rank DESC
LIMIT %(k)s;
"""


def hybrid_search(query: str, product: str | None = None, k: int | None = None) -> list[dict[str, Any]]:
    product = product or config.PRODUCT
    k = k or config.SEARCH_TOP_K
    try:
        qv = _vec_literal(embedder.embed_query(query))
    except Exception:
        # Embedder unreachable — degrade to lexical-only rather than failing the
        # whole search. Semantic quality is reduced, not the agent's ability to help.
        qv = None
    with connect() as conn:
        if qv is None:
            rows = conn.execute(_FTS_ONLY_SQL, {"q": query, "product": product, "k": k}).fetchall()
        else:
            rows = conn.execute(_HYBRID_SQL, {"qv": qv, "q": query, "product": product, "k": k}).fetchall()
    results = []
    for (title, heading, text, metadata, chunk_no, chunk_id, source_name,
         source_type, rrf, vec_sim, fts_rank) in rows:
        snippet = " ".join(text.split())
        if len(snippet) > config.SNIPPET_CHARS:
            snippet = snippet[: config.SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
        results.append({
            "title": title,
            "heading": heading,
            "text": text,          # full chunk — what the agent reads
            "snippet": snippet,    # capped — for CLI/debug display only
            "metadata": metadata if isinstance(metadata, dict) else json.loads(metadata or "{}"),
            "chunk_no": chunk_no,
            "chunk_id": chunk_id,
            "source": source_name,
            "source_type": source_type,
            "rrf": float(rrf),
            "vec_sim": float(vec_sim) if vec_sim is not None else None,
            "fts_rank": float(fts_rank) if fts_rank is not None else None,
        })
    return results


def is_weak(results: list[dict[str, Any]]) -> bool:
    if not results:
        return True
    top = results[0]
    semantically_far = top["vec_sim"] is None or top["vec_sim"] < config.SIM_FLOOR
    lexically_unmatched = top["fts_rank"] is None
    return semantically_far and lexically_unmatched


def status() -> dict[str, Any]:
    with connect() as conn:
        docs = conn.execute(
            "SELECT product_id, source_type, source_name, version, embed_model, "
            "       (SELECT count(*) FROM jacob.chunks WHERE document_id = d.id) AS chunks, ingested_at "
            "FROM jacob.documents d ORDER BY product_id, source_name"
        ).fetchall()
    return {
        "documents": [
            {"product": p, "type": t, "source": s, "version": v,
             "embed_model": m, "chunks": c, "ingested_at": str(ts)}
            for p, t, s, v, m, c, ts in docs
        ]
    }
