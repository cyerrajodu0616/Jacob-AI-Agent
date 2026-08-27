-- 0001_init — Jacob knowledge + conversation schema.
-- Lives in the "jacob" schema of the shared application database; never
-- touches other schemas. pgvector must already be installed on the server
-- (it is: 0.8.2) — extension installation is a DBA operation, not a migration.

-- ── knowledge side ───────────────────────────────────────────────────────────

CREATE TABLE jacob.products (
    id         TEXT PRIMARY KEY,                -- e.g. '511801'
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE jacob.documents (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id     TEXT NOT NULL REFERENCES jacob.products(id),
    source_type    TEXT NOT NULL CHECK (source_type IN ('pdf', 'json', 'md')),
    source_name    TEXT NOT NULL,
    title          TEXT,
    version        TEXT,
    effective_date DATE,
    checksum       TEXT NOT NULL,
    embed_model    TEXT NOT NULL,
    embed_dim      INT  NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded')),
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, source_name)
);

CREATE TABLE jacob.chunks (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES jacob.documents(id) ON DELETE CASCADE,
    product_id  TEXT   NOT NULL REFERENCES jacob.products(id),
    chunk_no    INT    NOT NULL,
    title       TEXT   NOT NULL,
    heading     TEXT   NOT NULL DEFAULT '',
    chunk_text  TEXT   NOT NULL,
    token_est   INT,
    metadata    JSONB  NOT NULL DEFAULT '{}'::jsonb,
    tsv         tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', title || ' ' || heading || ' ' || chunk_text)
                ) STORED,
    -- dimension bound to mxbai-embed-large; a model change is a migration + re-embed
    embedding   vector(1024) NOT NULL,
    UNIQUE (document_id, chunk_no)
);

CREATE INDEX chunks_tsv_idx     ON jacob.chunks USING gin (tsv);
CREATE INDEX chunks_vec_idx     ON jacob.chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_product_idx ON jacob.chunks (product_id);

-- ── conversation / audit side (logging wired by the app in a later change) ──

CREATE TABLE jacob.conversations (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id TEXT REFERENCES jacob.products(id),
    channel    TEXT NOT NULL CHECK (channel IN ('terminal', 'canvas', 'message_center')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at   TIMESTAMPTZ
);

CREATE TABLE jacob.turns (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES jacob.conversations(id) ON DELETE CASCADE,
    turn_no         INT  NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    decision        TEXT NOT NULL CHECK (decision IN ('answered', 'not_covered', 'out_of_scope', 'escalated', 'error')),
    model           TEXT,
    cost_usd        NUMERIC(10, 6),
    latency_ms      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, turn_no)
);

-- Which knowledge grounded which answer. chunk_id survives as a live link while
-- the chunk exists; the snapshot columns preserve the audit when re-ingestion
-- replaces chunks (ON DELETE SET NULL, never lose the record).
CREATE TABLE jacob.turn_sources (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    turn_id     BIGINT NOT NULL REFERENCES jacob.turns(id) ON DELETE CASCADE,
    chunk_id    BIGINT REFERENCES jacob.chunks(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    title       TEXT NOT NULL,
    heading     TEXT NOT NULL DEFAULT '',
    rank        INT  NOT NULL,
    rrf         DOUBLE PRECISION,
    vec_sim     DOUBLE PRECISION,
    fts_rank    DOUBLE PRECISION
);
CREATE INDEX turn_sources_turn_idx ON jacob.turn_sources (turn_id);

CREATE TABLE jacob.escalations (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    turn_id    BIGINT NOT NULL REFERENCES jacob.turns(id) ON DELETE CASCADE,
    reason     TEXT NOT NULL,
    summary    TEXT NOT NULL DEFAULT '',
    context    TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'routed', 'closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── seed: the pilot product ──────────────────────────────────────────────────
INSERT INTO jacob.products (id, name) VALUES ('511801', 'Product 511801')
ON CONFLICT (id) DO NOTHING;
