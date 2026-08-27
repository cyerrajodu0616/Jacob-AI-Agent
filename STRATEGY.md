# Jacob — Support Strategy (grounded in real ticket data)

**Purpose:** decide what Jacob should actually be, based on what agents actually
contact support about — not on what a knowledge base happens to be good at.

**TL;DR:** A knowledge-answering bot (what we've built) addresses roughly
**10–15% of real eApp support demand.** The majority of tickets need a *live look
at a specific application*, are *system bugs*, or *belong to another team*. The
highest-leverage next capabilities are **live application-state lookup** and
**smart triage/routing** — not more product content.

---

## 1. What we analyzed

- **Source:** a HubSpot export of **19,607 support tickets** (subjects + bodies;
  92% have a description, 32% have a resolution note).
- **Scope:** the tickets span many products (SBLI, Quility, LWP, and others).
  **~11,900 are eApp/agent-related; 393 are NewBridge/511801-specific.** The
  NewBridge slice is small, but the patterns are the same across products — an
  agent stuck submitting an application has the same problem regardless of
  carrier — so we design for the eApp pattern and it applies to 511801.
- **Method:** keyword/theme classification over ticket bodies, plus analysis of
  the resolution notes, plus manual reading of PII-redacted samples per category.
- **Caveats:** classifications are keyword-based and **overlapping** (a ticket can
  be both "stuck" and "signature"), so category counts don't sum to a clean
  total; treat them as *shape*, not precise percentages. The corpus also carries
  noise (email signature blocks, threading artifacts). No client PII is reproduced
  here; raw data was handled in a gitignored scratchpad only.

---

## 2. What agents actually contact support about

Four categories, sorted by *what it would take to resolve them*. Counts are over
the ~11,900 eApp tickets (overlapping tags).

### A. Needs a live look at the specific application — ~32% (the single biggest need)
> *"Why was this client declined?"* · *"declined for 'carrier ineligible' — I'm
> trying to determine the reason"* · *"what's the status of my pending app?"* ·
> *"the rate changed from $47.50 to $55.55 on approval — why?"* · *"the client
> isn't receiving the signature link"* · *"can I get copies of these ARC
> applications?"*

A document cannot answer these. They're about **one application's actual state** —
its decision code, underwriting reason, assigned rate class, delivery status,
documents. This is exactly what a retrieval/knowledge bot *cannot* do, and it's
the most repeated thing agents ask.

### B. System bugs / outages — ~31%
> *"Technical error, told to start a new app"* · *"the ROP option is greyed out
> for everyone in the right age/rate class"* · *"the SMS resend button
> disappeared"* · *"the customer can't clear the 'Thanks for applying' splash
> screen"* · *"the link is temporarily down."*

Real defects and outages. They need engineering, not an answer. Jacob's only
useful role here is to **recognize the pattern and report/flag it**, never to
pretend it has a fix.

### C. Route elsewhere / out of scope — ~29%
> Login / password / locked account · *"I'm not appointed / how did I lose my
> appointment?"* · *"I haven't received my agent writing number"* · *"I only have
> the final-expense contract, I need all products"* · account setup.

These belong to **Contracting & Licensing, IT, or portal admin** — not eApp
product support. Jacob should **recognize and route with a captured summary**, not
attempt an answer.

### D. Knowledge-answerable — Jacob's actual sweet spot — ~11%
> *"Is it age nearest or age last?"* · *"How do I add a split-commission agent
> number?"* · *"I checked the wrong box on the application — can I redo it?"* ·
> *"What does this message mean?"* · eligibility and product questions.

Small but real — and **exactly what we've built and validated Jacob doing well**
(retrieval + grounded answers + the confidentiality/no-compute rules).

*(A residual ~34% tagged "unclear" is mostly general status/follow-up and noise;
deeper reading would split it mostly across A and C.)*

---

## 3. How support *actually* resolves tickets (the decisive finding)

Of the 6,354 tickets with resolution notes:

| Resolution action | ~count |
|---|---|
| Reset access / unlock / re-enable | ~1,124 |
| Backend or manual fix | ~178 |
| Escalated / forwarded to a team | ~210 |
| Resent a link / OTP | ~65 |
| **Advised / explained (pure guidance)** | **~57** |
| Duplicate / no action / closed | ~130 |

**Support work is overwhelmingly *actions*, not *answers*.** Only ~1% of resolved
tickets were closed by explaining something. Agents mostly need someone to **do**
something — reset, fix, resend, escalate — which a knowledge bot cannot do. This
is the clearest signal in the whole dataset.

---

## 4. Strategic implications for Jacob

1. **A pure RAG knowledge bot tops out at ~10–15% of real support volume.** What
   we built is genuinely good and correct — and genuinely a *slice*, not the
   product. It is the foundation, not the destination.
2. **The highest-leverage capability is live application state.** "Why is my app
   declined / what's its status" is the #1 recurring need and the one thing a
   knowledge bot structurally can't do. It requires **read access to the
   application/arc data** (decision codes, underwriting results, rate class,
   delivery status, documents), scoped read-only and PII-aware.
3. **The second is smart triage/routing.** ~60% of tickets (bugs + out-of-scope)
   are things Jacob *shouldn't answer*. The win is recognizing them and handing
   off to the right team/queue *with context*, rather than fumbling — plus
   surfacing recurring bugs to engineering.
4. **Content depth serves the answerable ~11% and makes deflection graceful.**
   Necessary, not sufficient.
5. **Real agent messages are nothing like clean Q&A.** They're informal,
   frustrated, typo-ridden, context-thin — often just an arcId and "why
   declined?", with client names and signatures pasted in. Jacob's handling and
   any future evals must reflect that reality, not idealized questions.

---

## 5. Recommended reframe and roadmap

Reframe Jacob from **"product FAQ bot"** to **"eApp support triage + assistant."**
Capabilities in priority order (by real demand):

### Track 1 — Live application-state lookup *(biggest lever)*
A read-only tool that, given an arcId (or the agent's current application),
returns its state: current step, decision/UW outcome and reason, assigned rate
class, e-sign/consent delivery status, documents. This turns the #1 category
("why is my app declined / where is it") from unanswerable into Jacob's strongest
feature. **Requires:** read access to the arc/application system, careful PII
handling, and a clear scope of what's safe to surface to an agent vs. what's
confidential (underwriting internals stay hidden — same rule we already enforce).

### Track 2 — Triage & routing *(deflect the ~60% Jacob shouldn't answer)*
Jacob classifies each message: answerable → answer; live-state → look it up
(Track 1); bug → capture + flag to engineering; out-of-scope → route to the right
team (Contracting & Licensing, IT/portal) with a summary. **Requires:** a small
"who owns what" directory and a handoff mechanism (the escalation tool, evolved
into a router). Handles the biggest chunk of volume cleanly without pretending to
solve it.

### Track 3 — Content depth + graceful deflection *(the answerable ~11%)*
Extend the KB toward the real answerable questions from the tickets — procedural
how-to (split commission, redo/edit an application, resume), eligibility/age-basis
clarifications, and "what this message means → next step." Grow the eval set to
match *real* agent phrasing, not idealized questions.

---

## 6. Open questions to resolve next

- **Which system holds the live application state**, and can Jacob get scoped
  read access? (Decision codes, UW reasons, delivery status likely live in the
  arc systems / the same data behind the eApp and DomRecorder.)
- **What is safe to tell an agent about a decline** vs. what's confidential
  underwriting detail? (The line we already drew for static content applies.)
- **The routing directory:** who owns login/access, contracting/licensing,
  billing, and engineering-grade bugs — and how does a handoff reach them
  (especially before the Message Center is live)?
- **The recurring "link/text not received" problem** appears across categories
  and is often phrased as a bug ("2nd time this week", "multiple clients
  tonight") — is there an underlying delivery reliability issue worth flagging on
  its own?

---

## 7. Bottom line

The knowledge base we built is correct, validated, and useful — and it is the
**~11% + the foundation**, not the whole job. The data says the real product is
**triage + live application state**. That's the bridge to the "real
application-level" work, and it's where the support volume actually is.
