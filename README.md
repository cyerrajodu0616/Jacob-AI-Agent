# Jacob AI Agent

A minimal Claude agent. One file, one system prompt, no tools. Runs on the
**Claude subscription login** (no API key, $0 to run).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
claude login          # one-time, if not already logged in
unset ANTHROPIC_API_KEY
```

## Run

```bash
python agent.py                          # chat (replies stream live)
python agent.py "What is a monorepo?"    # one-shot
```

In-chat commands: `/new` starts a fresh conversation, `/quit` (or Ctrl-D) exits.

## What's here

- `agent.py` — the conversation agent: one `ClaudeSDKClient` session per
  conversation, live-streamed replies, grounded via the `search_knowledge_base`
  tool. Hermetic (`setting_sources=[]`), Sonnet-pinned (`JACOB_MODEL` overrides),
  refuses to start if `ANTHROPIC_API_KEY` is set. **Imports no DB drivers** — its
  only capability is the knowledge tool, served by a separate process.
- `canvas.py` — live build canvas + chat at http://127.0.0.1:8712 (n8n-style
  board introspected from the code; chat panel drives a real session).

### Data-access boundary

The agent (and canvas) process holds **no database or embedder connection**. The
one tool it can call, `search_knowledge_base`, runs in a **separate process**
(`rag/server.py`) that the SDK spawns over stdio (MCP). That subprocess is the
only place Postgres/Ollama are ever touched — the agent cannot reach the database
directly, by construction.

- **`rag/`** — the **runtime retrieval layer** (in the MCP server process):
  - `rag/server.py` — the out-of-process MCP server exposing `search_knowledge_base`.
  - `rag/store.py` — Postgres + pgvector: `documents` / `chunks`, hybrid
    retrieval (pgvector cosine + full-text, RRF-fused), weak-match gate.
  - `rag/embedder.py` — Ollama `/api/embed` client (`mxbai-embed-large`, 1024d);
    host set by `JACOB_EMBED_BASE_URL` in `.env`.
- **`rag/ingest/`** — the **build-time pipeline** (runs only when knowledge changes):
  - `python -m rag.ingest` — CLI: `init` / `add` / `search` / `status` / `remove`;
    checksum-idempotent; PDF + markdown.
  - `rag/ingest/chunker.py` — heading-aware PDF chunker.
  - `rag/ingest/migrate.py` — versioned SQL migrations (`db/migrations/`).
- `scripts/build_pdf.py` — combine the `docs/*.md` sources into one guide PDF.

## Knowledge ops (run from the repo root)

```bash
python -m rag.ingest add --product 511801 knowledge/511801/docs/*.md   # md sections = chunks
python -m rag.ingest search --product 511801 "some question"   # debug retrieval
python -m rag.ingest status
python -m rag.ingest.migrate                                          # apply schema
```

The markdown docs are the ingest source (one chunk per `##` section). The guide
PDF built by `scripts/build_pdf.py` is a human-readable artifact, not the corpus
— PDF text extraction fractures tables/headings and measurably hurt retrieval.

Postgres: shared dev instance, schema `jacob` (`JACOB_DB_DSN` in `.env`).

## Evals

```bash
python -m evals.run appstate    # live-state projection vs synthetic memApps (no model, no cost)
python -m evals.run retrieval   # RAG pipeline: right section + weak gate (no model, no cost)
python -m evals.run agent       # Jacob's behavior: grounded / refuses / confidential / no-compute (uses the model)
python -m evals.run all
```

Cases live in `evals/cases.py` + `evals/appstate_cases.py` (~135 total) — each
pins a decision we made (a correct fact, a refusal, a confidentiality boundary,
the no-compute rule). Non-zero exit on any failure, so it works as a gate.
Filter the agent tier by name, e.g. `python -m evals.run agent riders,payor`.

### The sweep — 1,000-question bank

The deep tier: `evals/bank/*.jsonl` holds **1,000 graded questions** written the
way agents actually write (typos, missing context, pasted arcIds), each with a
ground-truth rubric grounded in the KB docs or the synthetic live-state
fixtures. Covers product facts, screens/journey, premium no-compute traps,
confidentiality + prompt-injection, not-covered honesty, handoffs, routing, bug
reports, and **live application-state lookups** (the agent's `get_application_state`
tool runs against `evals/mockplatform.py` serving `evals/fixtures.py` — zero
contact with the real platform).

```bash
python -m evals.sweep            # ask pass: fresh session per question, checkpointed + resumable
python -m evals.judge            # judge pass: predicates + haiku judge, sonnet on escalation
python -m evals.report --md      # scoreboard, failure list, report.md
# rerun just the failures:
python -m evals.sweep --ids evals/sweep-results/failed_ids.txt --redo
```

Results land in `evals/sweep-results/` (gitignored): `answers.jsonl`,
`verdicts.jsonl`, `report.md`. Both passes checkpoint per item, so interrupts
and rate-limit pauses resume for free.

- Not here yet: escalation tool, Message Center integration, multi-turn sweep
  cases (every bank question is single-message by design).
