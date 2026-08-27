"""RAG retrieval layer — runs at QUERY TIME (every search) and at ingest time.

    store.py     hybrid search + Postgres/pgvector storage
    embedder.py  embeddings (embeds the question at query time, chunks at ingest)

The build-time-only pipeline (CLI, chunker, DB migrations) lives in rag/ingest/
and never runs during a user conversation.
"""
