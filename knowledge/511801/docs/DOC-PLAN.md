# 511801 Agent-Facing Documentation Plan

Curated knowledge base content for Jacob, written for licensed agents using the
eApp. This folder is the approved corpus; drafts do NOT get ingested until
approved.

## Where files live

- **`knowledge/511801/docs/`** — the seven approved markdown sources. These are
  **ingested directly** (`python -m rag.ingest add --product 511801
  knowledge/511801/docs/*.md`) — one chunk per `##` section.
- **`knowledge/511801/`** — the combined guide PDF built from the sources by
  `scripts/build_pdf.py`. Human-readable artifact only; **not** the ingest
  source anymore (PDF text extraction fractured the coverage matrix and screen
  headings into fragments, which the 1,000-case sweep caught as retrieval
  failures).

## Conventions

- One topic per file; `#` title + `##` sections (the chunker splits on `##`).
- Written in the agent's language: plain names, no internal codes, config keys,
  page IDs, or internal URLs. Nothing confidential (no underwriting mechanics,
  vendors, thresholds).
- Numbers must match the published sources exactly — never derived.
- Unconfirmed claims carry a `[VERIFY: question]` marker; ingestion refuses any
  file that still contains one.
- Lifecycle per doc: **draft (docs/) → reviewed → approved (moved up) → ingested**.

## Documents

| # | File | Status | Primary source |
|---|------|--------|----------------|
| 1 | product-overview.md | reviewed — gaps filled from PDF | spec PDF p.1–2 |
| 2 | coverage-and-eligibility.md | reviewed — gaps filled from PDF | control JSON + PDF p.1–2 |
| 3 | application-process.md | **approved & ingested** | production DomRecorder + SME confirmation |
| 3b | application-screens.md | draft — review me | aff-ui-511801-az page components |
| 4 | rate-classes.md | todo | control JSON + PDF p.2 |
| 5 | premiums-and-payment.md | todo | PDF tables + control JSON |
| 6 | state-availability.md | todo | control JSON |
| 7 | riders.md | todo | PDF p.3 + control JSON |
| 8 | decisions-and-statuses.md | todo — needs SME review | control JSON comeback msgs + you |
| 9 | timelines-and-validity.md | todo | control JSON |
| 10 | troubleshooting-and-errors.md | todo — needs SME input | control JSON + you |
| 11 | client-communications.md | todo | control JSON templates |

## Sweep-driven edits (2026-08-23) — content-preserving, for SME review

Made while hardening Jacob against the 1,000-case sweep; every fact unchanged,
only structure/vocabulary for retrieval:

- **product-overview.md** — split the overloaded "Key product rules" into three
  `##` sections (premiums/maturity · replacements/reinstatement/conversion ·
  grace/contestability/misstatement); added a leading "Product type: whole life
  insurance…" line to "What this product is"; misstatement bullet gained the
  parenthetical "(a wrong date of birth or gender on the application)";
  conversion bullet gained "— the policy cannot be converted to another
  product".
- **coverage-and-eligibility.md** — pulled the state list out of "Eligibility
  basics" into its own "## State availability" section; added the
  ZIP-drives-state sentence (already documented in application-screens.md).

Batch 2 (same day, after the run-2 failure triage):

- **product-overview.md** — new "## Carrier" section (fact unchanged: Continental
  General); "Licensing" renamed/enriched to "Licensing, contracting and
  appointment — who to contact" with the vocabulary agents actually use
  (appointment, writing number, downline, hierarchy, renewals) around the same
  contact; misstatement bullet now phrased around the insured dying with a wrong
  DOB/gender (same rule).
- **application-process.md** — new "## Pausing and resuming an application"
  section consolidating three already-published facts (answers save as entered;
  identity routes to resume; 30-day timeout).
- **cash-value-and-provisions.md** — ETI bullet now says "stops paying premiums
  entirely" (vocabulary only).
- **application-screens.md** — CG100 gained the "Pending Issue" sentence already
  published in application-process.md.

Batch 3 (2026-08-23, SME dictation — starting-stage corrections):

- **application-process.md** — starting order corrected per SME: lead form
  (QO100) → **pre-application assessment (MS100)** → quote (QO105) → confirm
  eligibility (QO110, agent verification runs on Next) → "Before You Begin"
  producer questions (QO115) → security warning (QO120) → start application →
  interview. (MS100 previously documented after the quote screen.)
- **application-screens.md** — QO100/QO105/MS100 neighbor references updated to
  the corrected order; QO115 gained its on-screen title ("Before You Begin:
  Questions for Producer"); **QO110 now carries the full on-screen eligibility
  checklist verbatim** (3 criteria + the complete pre-qualifying condition
  list + the confirmation statement) — SME-dictated agent-facing screen text,
  which turns "can my client with X apply?" questions into grounded answers.

## Open SME questions

Collected per doc as we go; answered items fold into the doc.

- ~~premiums-and-payment.md — third-party payor conflict~~ RESOLVED: the live
  eApp governs — payor can be applicant, spouse, or domestic partner (the older
  premium spec sheet said insured/spouse only; superseded). Documented.
- **Excluded as confidential/internal (by design):** underwriting methods
  (Milliman Irix risk score, prescription/medical data, MIB, build charts); the
  modal-premium formula and modal factors as a calculation recipe (Jacob is
  non-computational for premiums); "Afficiency → Sapiens" config notes; the
  "commissionable" fee note; Social Security Express Debit (Day-2, not live).

- ~~**application-process.md**: what is page MS100 for?~~ RESOLVED from the UI
  code: MS100 is the **Assessment Result** interstitial shown right after the
  quote (good fit / not likely eligible / neutral). Documented in
  application-screens.md.
