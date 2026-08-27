"""Build-time knowledge pipeline — runs ONLY when knowledge is added or updated,
never during a user conversation.

    __main__.py  the CLI:  python -m rag.ingest  (init / add / search / status / remove)
    chunker.py   PDF → chunks
    migrate.py   versioned SQL migrations (db/migrations/)

It uses the runtime retrieval layer (rag/store.py, rag/embedder.py) to write and
embed; those two modules are the only pieces shared with query time.
"""
