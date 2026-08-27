# Jacob AI Agent — Project Context

A complete reference for the Jacob RAG support agent (product 511801). Written to
onboard a new engineer, or to remember why things are the way they are.

---

## 1. What this is

Jacob is an AI support assistant for **licensed insurance agents** working inside
the **NewBridge Final Expense (product 511801)** eApp. An agent, mid-application
with a client, messages Jacob the way they'd message a helpful colleague. Jacob:

- answers **only** from an approved knowledge base, in a short, human tone;
- **refuses or hands off** when it can't ground an answer, when the question is
  confidential (underwriting internals, fraud rules), or out of scope
  (approval odds, suitability, legal/tax/medical advice);
- **never computes** premium figures — those come from the eApp's quote screen.

It is designed to eventually plug into the human-to-human **Message Center**,
which owns conversation storage. This repo is the agent's brain + its knowledge
pipeline, not the production integration.

---

## 2. Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
claude login            # one-time subscription login
unset ANTHROPIC_API_KEY # the agent refuses to start if this is set

# talk to Jacob
python agent.py                         # terminal chat  (/new, /quit)
python agent.py "What riders are available?"   # one-shot

# live board + chat in a browser
python canvas.py        # → http://127.0.0.1:8712
```

Prerequisites at runtime: the `claude` CLI (subscription auth), a reachable
Postgres (`JACOB_DB_DSN`), and a reachable Ollama embedder (`JACOB_EMBED_BASE_URL`).

---

## 3. Architecture

### The data-access boundary (the central design decision)

The agent process holds **no database or embedder connection**. Its only
capability is one MCP tool, `search_knowledge_base`, which runs in a **separate
process** that the SDK spawns over stdio. That subprocess is the only place
Postgres and Ollama are ever touched.

```
you ─► agent.py / canvas.py            ← imports NO data drivers (verified)
          │  MCP over stdio  (spawned by the claude CLI)
          ▼
      rag/server.py                     ← the ONLY process with the DB/embedder
          ▼
   Postgres (jacob schema, read-only)  +  Ollama (embeddings)
```

The agent cannot reach the database by construction — no driver is loaded, and
its tool allow-list contains exactly one entry. This is enforced at the **process
level**, not just the model level.

Additional guardrails on the agent session (`agent.py` → `build_options`):

- `setting_sources=[]` — hermetic; ignores any machine `CLAUDE.md`, settings, or
  ambient MCP servers.
- `allowed_tools=["mcp__jacob__search_knowledge_base"]` + `permission_mode="dontAsk"`
  — every other tool (bash, file read/write, web) is silently denied.
- refuses to start if `ANTHROPIC_API_KEY` is set (subscription-only).
- `model="claude-sonnet-5"` (via `JACOB_MODEL`), `max_turns=8`, streaming on.

### Two lifecycles: runtime vs build-time

| When | What runs | Files |
|---|---|---|
| **Every question** | embed the query → hybrid search → return labelled sources | `rag/server.py`, `rag/store.py`, `rag/embedder.py` |
| **Only when knowledge changes** | chunk → embed → upsert; schema migrations | `rag/ingest/` |

`store.py` and `embedder.py` live at `rag/` top level because they are **shared**
by both paths (you must embed the query with the same model and schema that
embedded the chunks). The build-time-only pieces are isolated in `rag/ingest/`.

---

## 4. File-by-file reference

```
agent.py            The conversation agent. ClaudeSDKClient, streaming reply
                    loop, /new + /quit, one-shot mode. Declares the out-of-process
                    MCP server (stdio) and the tool allow-list. Loads the system
                    prompt fresh each session. Imports NO data drivers.

config.py           Central settings, all env-overridable, loads .env:
                    PRODUCT, PRODUCT_NAME, CARRIER_NAME, DB_DSN, EMBED_* ,
                    SEARCH_TOP_K, SIM_FLOOR, SNIPPET_CHARS.

canvas.py           Dev tool: a zero-dependency HTTP server at :8712 that (a)
                    renders an n8n-style board by AST-parsing agent.py live, and
                    (b) hosts a real ClaudeSDKClient chat (streamed, typewriter
                    rendering, /new). Imports no data drivers either.

prompts/system.md   Jacob's persona and rules — a versioned artifact, not code.
                    Loaded fresh per session, so edits apply on the next /new.

rag/                RUNTIME retrieval layer:
  server.py         The out-of-process MCP server. Exposes search_knowledge_base
                    (mcp 2.0 MCPServer, stdio). The only process importing store.
  store.py          Postgres + pgvector. Schema-qualified queries, the hybrid
                    search (vector cosine + full-text, RRF-fused), the weak-match
                    gate, and the ingest upsert/remove helpers.
  embedder.py       Ollama /api/embed client (mxbai-embed-large, 1024-dim). Uses
                    certifi (python.org 3.14 ships without CA certs).

rag/ingest/         BUILD-TIME pipeline:
  __main__.py       CLI:  python -m rag.ingest  {init|add|search|status|remove}.
                    Checksum-idempotent; markdown + PDF; refuses files with
                    unresolved [VERIFY:] markers.
  chunker.py        Heading-aware PDF chunker (works on any prose PDF's own text).
  migrate.py        Versioned SQL migration runner (python -m rag.ingest.migrate).

db/migrations/      0001_init.sql, 0002_drop_conversation_audit.sql

scripts/build_pdf.py  Combine knowledge/511801/docs/*.md into the guide PDF
                    (markdown → HTML → headless-Chrome PDF).

evals/              cases.py (~105 cases) + run.py (retrieval + agent tiers).

knowledge/511801/
  NewBridge-Final-Expense-511801-Agent-Guide.pdf   ← the ingested source
  docs/            ← the 7 markdown sources + DOC-PLAN.md (build-tracking)
```

---

## 5. Knowledge base

### Source of truth and pipeline

Seven curated **agent-facing** markdown docs live in `knowledge/511801/docs/`.
**The markdown files are what gets ingested** — one chunk per `##` section, so
every chunk has a real heading and a coherent body:

```
docs/*.md ──rag.ingest add──► 62 chunks in Postgres   (build_pdf.py still builds
                                                       the human-readable guide PDF)
```

> History: the combined guide PDF used to be the ingest source. The 1,000-case
> sweep exposed why that was wrong: the PDF text extractor fractured the
> coverage-by-age matrix across four fragment chunks (wrapped lines became
> headings) and collapsed all 31 screen sections into one generic heading —
> retrieval returned fragments, and Jacob honestly refused facts that were "in"
> the KB. Ingesting the markdown directly fixed the whole cluster (coverage
> category: 71.9% → see sweep report). The PDF remains a human artifact only.

Current state: **7 documents → 62 chunks**. Each chunk carries its section
heading, a generated full-text vector, and a 1024-dim embedding.

### The docs (all approved)

1. `product-overview.md` — what it is, death benefit types, who's covered, key rules, licensing.
2. `coverage-and-eligibility.md` — coverage range, max-by-age matrix, issue ages, states.
3. `riders.md` — ADBR (free) and the AD rider; child rider not offered.
4. `cash-value-and-provisions.md` — loans, surrenders, grace, non-forfeiture.
5. `premiums-and-payment.md` — methods, payor, modes, draft dates, increase/decrease, fee.
6. `application-process.md` — the end-to-end journey (page codes + hand-offs).
7. `application-screens.md` — a per-screen guide (QO100 → CG100 + branch pages).

### How the content was built (provenance)

The content was **not** written from general insurance knowledge. It was derived
and verified from real sources:

- The carrier **spec PDF** (product specifications + premium tables) and the eApp
  **control JSON** — audited section-by-section against screenshots, with real
  gaps found and corrected (the modified-benefit graded schedule, tobacco/
  benefit-type issue ages, maturity age 121).
- The **application journey** was reconstructed from **production DomRecorder
  session recordings** (real arcId ARCF26233P685, page-code sequence only, no
  PII), then confirmed by the SME (the user).
- The **per-screen guide** was built by reading the `aff-ui-511801-az` React
  page components + the eApp config, then verified against the actual code.

The original spec PDF and control JSON have since been removed; the combined
agent-guide PDF is the single ingest source. `docs/DOC-PLAN.md` tracks the
lifecycle (draft → reviewed → approved → ingested) and any open questions.

---

## 6. Database schema (`jacob` schema, shared dev Postgres `arcdb`)

Everything is namespaced under the `jacob` schema so it never touches the arc
application's tables. Managed by versioned SQL migrations.

Live tables:

| Table | Rows | Purpose |
|---|---|---|
| `products` | 1 | product registry (`511801`) |
| `documents` | 1 | one row per ingested source (checksum → idempotent re-ingest) |
| `chunks` | 43 | the retrieval unit: text + metadata + `tsvector` (GIN) + `vector(1024)` (HNSW) |
| `schema_migrations` | 2 | applied-migration tracking |

**Retrieval** = for each query: pgvector cosine similarity **and** Postgres
full-text, fused with reciprocal-rank fusion (RRF, k=60), filtered to the
product, top-k. A **weak-match gate** (`SIM_FLOOR=0.55`) marks a result "not
covered" when the best hit is both semantically distant and lexically unmatched,
which drives Jacob's ground-or-escalate behavior.

**Migration 0002** dropped the originally-designed conversation/audit tables
(`conversations`, `turns`, `turn_sources`, `escalations`) — the Message Center
owns conversation storage. `escalations` will be re-created by the escalation
tool's own migration when that feature is built.

---

## 7. Persona and behavior (`prompts/system.md`)

- **Voice:** like a person, 1–3 sentences, answer first, plain text, no headings/
  tables unless asked, no meta-narration, no reflexive closing offers.
- **Grounding:** search silently before answering; say only what retrieval
  supports; results are labelled STRONG / MODERATE / WEAK and Jacob answers only
  from strong matches, treating weak as not-covered.
- **Numbers are quote-only, never computed** — no scaling, converting, or
  prorating premiums; unpublished figures defer to the eApp quote screen.
- **Confidential (never exposed):** underwriting mechanics (data sources,
  vendors, risk scores — e.g. Milliman/MIB), fraud/ID rules and thresholds,
  internal codes/page-IDs/config/URLs.
- **Out of scope → hand off to a human:** applicant approval odds, product
  suitability, legal/tax/medical/financial advice.
- **Structure discipline:** never invent orderings/groupings the content doesn't
  state (a list of steps is a set, not a sequence, unless the source says so).

---

## 8. Configuration (`.env`, gitignored)

| Key | Meaning |
|---|---|
| `JACOB_DB_DSN` | Postgres connection (shared dev `arcdb`, schema `jacob`, sslmode=require) |
| `JACOB_EMBED_BASE_URL` | Ollama host serving `mxbai-embed-large` |
| `JACOB_MODEL` | override the pinned `claude-sonnet-5` |
| `JACOB_PRODUCT` | product id (default `511801`) |
| `JACOB_SIM_FLOOR` | weak-gate cosine floor (default `0.55`) |

Embeddings run on Ollama (`mxbai-embed-large`, 1024-dim), reached over HTTP.
Ollama is a separate service kept warm across sessions; the embedder is a clean
seam, so swapping to an in-process model later is a one-file change.

---

## 9. Evals (`python -m evals.run [retrieval|agent|all]`)

~105 cases, each pinning a decision made during the build. Non-zero exit on any
failure → usable as a gate.

- **Retrieval — 46/46** — validates the pipeline (right section in the top-k set,
  weak-gate on off-topic queries). Needs Postgres + Ollama; **no model, no cost**;
  runs in ~30s.
- **Agent — 59/59** — validates Jacob's behavior across grounded facts, no-compute
  premium refusals, out-of-scope handoffs, confidentiality (no leak of Milliman/
  MIB/risk-score), and honest "not covered". Fresh session per case; uses the
  model (~15 min). Filter a subset: `python -m evals.run agent riders,payor`.

Building the suite surfaced the standard eval-calibration loop: the initial
"failures" were too-strict assertions, not agent/pipeline bugs (e.g. checking
only the #1 retrieval result instead of the top-k set; keyword lists that missed
correct-but-differently-phrased answers). One genuine minor finding is noted: the
one-line product-type overview chunk only retrieves with lexical overlap.

### The sweep — the 1,000-question bank (`evals/bank/`)

The deep behavioral tier, built after the STRATEGY reframe so the eval matches
*real* support traffic, not idealized Q&A:

- **`evals/bank/*.jsonl`** — 1,000 cases, each with an `id`, a `behavior`
  contract (answer / correct_premise / no_compute / not_covered / refuse_uw /
  handoff / route / bug / lookup / ask_arcid / resist_injection), a ground-truth
  `rubric`, and optional mechanical predicates. ~a quarter are deliberately
  informal/typo-ridden/context-thin (STRATEGY §5: real agent messages are
  nothing like clean Q&A). Grounding: the KB docs for static cases;
  `evals/fixtures.py` for live-state cases.
- **`evals/fixtures.py` + `evals/mockplatform.py`** — 12 synthetic memApps
  (approved-pending-signature, issued+packet, declined, referred UW, stuck
  consent, offer expired, under review, wrong product, ID-check stop,
  injection-in-status, plus not-found and HTTP-500 ids) served by a local HTTP
  stand-in for platform-infra. The sweep points `JACOB_PLATFORM_BASE_URL` at it,
  so the full agent → MCP → projection path runs with **zero real-platform
  contact**.
- **`evals/sweep.py`** — ask pass: fresh session per question (same isolation as
  `evals/run.py`), concurrency-capped, checkpointed to
  `sweep-results/answers.jsonl`, resumable, staged backoff on rate limits.
- **`evals/judge.py`** — three layers: mechanical predicates + hard-leak
  sentinels (Milliman/Irix/Sherlock/the internal product name — instant FAIL);
  a fast haiku judge on every answer; sonnet re-judging every disagreement or
  fast-judge FAIL. Verdicts checkpoint by (id, answer-hash).
- **`evals/report.py`** — scoreboard by category/behavior, full failure list,
  `failed_ids.txt` for targeted re-runs, `report.md`.

---

## 10. Validated product facts (511801) — quick reference

All grounded in the approved KB.

- **Product:** NewBridge Final Expense · **carrier:** Continental General ·
  **type:** simplified-issue, instant-decision **whole life** (the JSON's internal
  name "Avant" is never shown to agents).
- **Coverage:** min $2,000, max $35,000, $1,000 increments, default quote $2,000.
- **Max coverage by age/class:** <75 → Level $35k / Modified $20k; 75 → Level Pref
  $20k, Level Std $15k / Modified $10k; 76–80 similar; 81–85 → only Level Pref
  $20k, Level Non-Tobacco $15k.
- **Issue ages (age last birthday):** Level Non-Tobacco 50–85, Level Tobacco
  50–80; Modified Non-Tobacco 50–80, Modified Tobacco 50–75.
- **Rate classes:** Level Preferred, Level Non-Tobacco, Level Tobacco, Modified
  Non-Tobacco, Modified Tobacco.
- **Death benefit — Level:** full benefit in all years.
- **Death benefit — Modified (may vary by state):** Yr 1 = 110% of premiums paid,
  Yr 2 = 120%, Yr 3+ = 100% of face; **accident pays full face from day one**.
- **Premiums:** paid to age 100; **maturity age 121**; modes monthly/quarterly/
  semi-annual/annual; **$25 annual policy fee**. Premiums are **quote-only** —
  Jacob never computes them.
- **Payment:** bank draft (ACH) or debit/credit card; draft fail → direct bill.
  Payor = applicant, spouse, or domestic partner. Draft date: up to 1 month out,
  days 1–28, specific week+day, or Social-Security alignment.
- **Coverage changes:** increases not allowed (buy additional coverage);
  decreases allowed to the policy minimum.
- **Riders:** Accelerated Death Benefit Rider (Terminal Illness) — **free**, on
  both benefit types. Accidental Death rider — **optional/extra cost, Level only**,
  issue ages 50–80, $2k–$35k matching base, ends at 100. **No** child/grandchild
  rider.
- **Cash value:** loans against cash value at **8% fixed**, max = net cash value
  less unpaid premiums, min loan $500 / min payment $25; surrender → cash
  surrender value or refund of unearned premiums; **31-day grace**; statutory-max
  non-forfeiture rate; no premium loan option; **ETI** automatic with cash
  surrender optional.
- **Eligibility/rules:** owner must be the insured; beneficiaries = spouse,
  domestic partner, child, parent, sibling; citizenship/LPR asked; **47 states,
  not CA/FL/NY/SC**; no replacements/1035; reinstatement with statement of good
  health; standard contestability; misstatement adjusts the benefit; no
  conversion privilege.
- **Licensing:** Life (Life and Annuity) license; Contract & Licensing Team
  866-830-2181 / Licensing@cgic.com.
- **Application journey (page codes):** QO100 quote → QO105/110/115/120 quote
  details → IV100–120 identity & interview → **CO100 consent (agent sends
  email/SMS; applicant consents on their own screen)** → BE100 beneficiaries →
  DW100 decision wait → OF100 offer → PM100 payment → **SA100/SC100/SN100 sign
  (agent sends email/SMS; applicant reviews & e-signs)** → AC100 producer
  certificate → CG100 congratulations → "Pending Issue". MS100 = the assessment-
  result interstitial after the quote.

---

## 11. Design decisions & constraints (the "why")

- **Build solid, not interim** — no "for now" phases or placeholder tech; the
  final architecture up front.
- **Subscription-only, $0** — no API key anywhere; the agent refuses to run with
  one set.
- **DB access strictly through MCP** — enforced at the process boundary, not just
  the model.
- **Numbers never computed by Jacob** — quote engine is authoritative for
  premiums.
- **Nothing confidential surfaced to agents** — internal carrier/underwriting
  material is context for Jacob, not content for the agent.
- **Every KB fact grounded in a real source** — gaps are marked `[VERIFY]`,
  never guessed; ingestion refuses docs with unresolved markers.
- **Ollama stays** (for now) — the embedder is a seam; revisit if the deployment
  target changes.

---

## 12. Operational runbook

```bash
# rebuild the guide PDF after editing a source doc, then re-ingest
python scripts/build_pdf.py
python -m rag.ingest add --product 511801 knowledge/511801/NewBridge-Final-Expense-511801-Agent-Guide.pdf

# inspect / debug retrieval
python -m rag.ingest status
python -m rag.ingest search --product 511801 "some question"

# schema
python -m rag.ingest.migrate            # apply pending migrations
python -m rag.ingest init               # same (used at first setup)

# validate before shipping any change
python -m evals.run retrieval           # fast, free
python -m evals.run agent               # full behavioral pass (~15 min, uses the model)
```

---

## 13. Not built yet / roadmap

- **Escalation tool** (`escalate_to_human`) — Jacob currently says "a human will
  follow up" but records nothing. The tool would be a second `@tool` in
  `rag/server.py` writing to a (re-created) `jacob.escalations` table. Self-
  contained; the natural next build.
- **Message Center integration** — the real application-level step; needs the
  Message Center's bot/participant contract.
- **Remaining KB depth** (`DOC-PLAN.md`): rate-classes, full state list,
  decisions-and-statuses, timelines-and-validity, troubleshooting,
  client-communications.
- **Optional hardening:** HTTP standing-service for the MCP server (one warm
  server for many sessions), in-process embeddings (drop the Ollama service),
  per-turn logging if ever needed outside the Message Center.
