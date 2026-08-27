# Application Screens — NewBridge Final Expense (511801)

A page-by-page guide to the eApp screens. Each screen is listed with its code,
what the agent does there, what is entered or shown, and anything notable. Where
a screen "advances to the next step," the exact destination is decided by the
system from the applicant's answers.

## Quote input (QO100)

The opening lead form to start a quote and pre-application assessment ("Get a
quote and pre-approval assessment"). The agent enters the applicant's legal
first and last name, date of birth, gender at birth, residence ZIP code, and
whether they have used tobacco in the last 12 months. State of residence is
filled in automatically from the ZIP. **Next** goes to the pre-application
assessment (MS100), then the quote; there is no Back. Out-of-range age/tobacco
combinations, or a ZIP in a state where the product isn't offered, are blocked
with an inline error.

## Quote (QO105)

A quote builder to shape coverage and premium and see the price. The agent can
quote by coverage amount or by monthly premium (a toggle), enter the amount,
see each rate class with its premium, and turn on the optional Accidental Death
Benefit rider. A Policy Total card shows coverage, rate class, and the premium
with a Monthly/Annual switch. The Accelerated Death Benefit for Terminal Illness
rider is included at no cost. Changing the amount recalculates automatically.
**Next** continues to the Confirm-eligibility checklist (QO110); **Back**
returns to QO100.

## Assessment Result (MS100)

A brief pre-application assessment interstitial shown right after the quote
input / lead form (QO100), before the quote builder. It
displays one of three results: the applicant looks like a good fit; the
applicant is not likely to be eligible (with a suggestion to consider another
product); or a neutral "we couldn't complete an assessment, please proceed."
Actions are **Proceed to Application** and **Back**; on the "not likely
eligible" result the agent can instead abandon the quote. If the assessment
errors or is slow, it falls through to the neutral "proceed" state and never
blocks the agent.

## Confirm eligibility (QO110)

A checklist of eligibility conditions the agent must confirm they discussed with
the applicant, plus a switch: "I confirm that I have discussed these conditions
with my applicant and they meet ALL the above standards." **Next** is enabled
only after the switch is on. When Next is clicked, agent verification runs
behind the scenes before the producer questions.

The applicant must meet all three criteria to consider applying:

- Be a US citizen or permanent resident.
- Not be replacing an existing Continental General policy.
- Be applying and signing in their state of residence.

The applicant must NOT have any of the following conditions:

- Cardiomyopathy, heart failure, pulmonary hypertension, defibrillator
  implanted, cirrhosis of the liver, chronic pancreatitis.
- Chronic Obstructive Pulmonary Disease (COPD) with nicotine or tobacco use in
  any form.
- Alzheimer's, dementia, cognitive impairment, schizophrenia, ALS, Huntington's
  Chorea, cystic fibrosis, recurrent history of cancer.
- Diabetes with complications of heart or circulatory disorder, amputation,
  insulin shock, and/or diabetic coma.
- Received or pending to receive an organ or bone marrow transplant, stem cell
  treatment, renal dialysis, or paralyzed in two or more limbs.
- Diagnosed with AIDS (Acquired Immunodeficiency Syndrome) or tested positive
  for HIV.
- Heart surgery or cancer in the past 12 months.
- Felony conviction, incarcerated, alcohol or drug abuse treatment, illegal use
  of drugs, or suicide attempt in the past 24 months.
- Currently admitted to a hospital or long-term rehab facility, residing in a
  nursing home, assisted living, or skilled nursing facility, or receiving home
  health or hospice care.
- Requires assistance with bathing, dressing, toileting, eating, transferring,
  taking medications, or handling financial affairs.
- Requires use of a wheelchair, electric scooter, walker, or oxygen equipment.
- Diagnosed with a terminal illness.

These are the on-screen pre-qualifying conditions the agent reviews with the
applicant — an applicant with any of them does not meet the product's standards
to apply.

## Producer questions (QO115) — "Before You Begin: Questions for Producer"

Controlled-business disclosure questions about the agent's relationship to the
applicant: interview format (in person / virtual); whether the agent is the
proposed insured or related to them; and, if related, the relationship (self,
spouse/partner, child, grandchild, parent, sibling). **Next** stays disabled
until the required answers are given.

## Security warning (QO120)

A short security and privacy warning that must be acknowledged with an "I
Confirm" switch before continuing.

## About you — personal info (IV100)

Collects the applicant's core identity details: legal first/middle/last name,
Social Security number, gender, date of birth (age shown read-only), whether
they are a US citizen or legal permanent resident, country of birth (and state
of birth if the United States), and whether they have a driver's license (and if
so, its number and state). The SSN is checked for format and validity. If the
person already has an application in progress, the agent is routed to resume it.

## About you — contact information (IV105)

Collects the physical home address (with address autocomplete), a confirmation
that the applicant will sign in their state of residence (this screen is where
the client confirms they will sign in their own state), an optional separate
mailing address, email, mobile phone, whether it is a mobile phone, and — if
mobile — agreement to receive texts for eConsent/eSignature. The applicant's
email and phone can't match the agent's own. ZIP must match the state.

## About you — existing coverage (IV110)

Captures existing or pending life insurance and annuity coverage and, where
required, the replacement (NAIC) flow. The agent answers whether the applicant
has existing/pending coverage and whether this application is intended to replace
it, and can add a table of existing policies (company, contract number, type,
amount, year issued, replacement/financing). Some answer combinations trigger a
"hard stop" alert with an Abandon Application button; financing is not allowed.

## Health & lifestyle questions (IV115)

The dynamic health-and-lifestyle interview (underwriting questions). Questions
are served a page at a time and branch based on answers; content varies per
applicant. Answers save as they are entered, and unanswered required questions
block **Next** and scroll to the first missing item. When the interview is done,
**Next** goes to the review screen.

## Review your answers (IV120)

A consolidated, editable review of everything captured, grouped into expandable
sections (ID details, existing coverage, and each health/lifestyle section). A
sticky note reminds the agent that once past this screen the applicant's
responses can't be altered. **Next** submits the reviewed application.

## Collect party consent (CO100)

Where the applicant's consent is obtained so their information can be analyzed
and the medical exam skipped. The agent sends a consent request to the applicant
by **email or text**, the applicant opens the link and consents on their own
screen, and a PIN is issued. The agent verifies the PIN, ticks a certification,
then continues. **Next** is enabled only after the PIN is verified and the box
checked. If the applicant's email/phone can't be validated, a warning appears
and the agent may need to correct the details. If the applicant hasn't received
it, re-check the email/phone and resend, and have them check spam.

## Beneficiary assignment (BE100)

Add primary and contingent beneficiaries. For each: first and last name,
relationship to the applicant (spouse, domestic partner, child, parent,
sibling), date of birth, Social Security number, share percentage, and whether
primary or contingent. Primary shares must total 100%; if there are any
contingent beneficiaries, their shares must also total 100%.

## Underwriting decision (DW100)

A processing / decision-wait screen while the underwriting decision is
retrieved. If the decision isn't ready after several checks, a "Notify Me"
option lets the agent step away and be notified later. The screen then routes
automatically to the resulting page (offer, a report, a review step, ID
verification, and so on) — the outcome is shown on the destination page.

## Offer (OF100)

The approved offer, where final coverage and premium are confirmed ("Congrats,
the applicant has been approved"). The agent can adjust the coverage amount (or
base premium); the approved rate class is shown read-only, with the Accidental
Death Benefit rider toggle and a Policy Total card (Monthly/Annual). **Next**
accepts the offer and goes to payment. On load it re-checks age and may show a
warning or reroute if the applicant's age has changed.

## Payment (PM100)

Collects bank draft details, payer, schedule, and frequency. Payment method is
immediate draft, a chosen day of the month, a specific week-and-day of the
month, or Social Security benefits billing (matched to the SS deposit schedule).
Frequency is monthly or annually. The payer can be the applicant, spouse, or
domestic partner; if not the applicant, payer details are collected. Banking
information includes routing number, institution name, account number (entered
twice), and account type. Bank details are validated; if they don't validate the
agent is asked to re-check them.

## Secondary addressee (SA100)

Optionally names a secondary addressee who receives copies of past-due/lapse
notices. The agent answers whether to add one; if yes, enters that person's name
and mailing address. The fields only appear when "Yes" is selected.

## Split commissions (SC100)

Assigns commission split across producers. For each producer the agent enters an
Agent ID and a share percentage (the writing producer is pre-listed at 100%).
Each added agent is verified, and the total share must equal 100% to proceed.

## Collect eSignature (SN100)

Obtains the eSignature from the applicant (and the payer, if a different person).
The agent sends the request by **email or text**; the signer opens the link,
reviews the signature packet, and e-signs on their own screen, receiving a PIN.
The agent verifies each signer's PIN and ticks each certification before
continuing. The application times out 30 days after it was started, and each
signer needs their own email/phone (not the agent's).

## Producer certification (AC100)

The agent's own certification and eSignature step. The agent confirms the
controlled-business and existing-coverage/replacement answers, reviews the
commission-split summary, and acknowledges each required document (Application
for Whole Life Insurance, Modified Endowment Contract Disclosure, Terminal
Illness Accelerated Death Benefit Rider disclosure, and — in replacement cases —
the NAIC Replacement Notice), then applies their eSignature. The eSignature
button stays disabled until all required documents are acknowledged.

## Congratulations (CG100)

The success screen confirming the application was submitted. It shows the
applicant's name, the recurring monthly/annual premium, the base coverage, and
the Accidental Death Benefit rider amount (or "None"). The agent can start a new
application. After this screen a completed application typically sits in a
"Pending Issue" state while final processing happens.

## ID check (ID100)

Shown when the applicant's identity couldn't be verified. The agent re-checks
and corrects the personal information (name, SSN, date of birth, gender,
address). A red banner appears when this is the last identity-check attempt; a
further failure can close the application, with a note that the applicant must
wait several days before reapplying.

## MIB reask (MR100)

Shown when third-party data warrants re-asking some health questions. The agent
is advised to explain why to the applicant, then the flagged questions are
presented again. **Next** revalidates and moves to the decision step. Some
outcomes show an "unable to proceed" notice.

## Not eligible (IE100)

A "We're sorry — your applicant is not eligible for this product" screen. It
offers an Important Customer Notice and a link to the underwriting eligibility
report, plus Close Application.

## Age ineligible (IE150)

A short "We're sorry" screen stating the applicant's age exceeds the maximum for
an eligible rate class. The only action is to close the application.

## Underwriting eligibility report (UW100)

A producer-facing screen to share the detailed underwriting report with the
applicant. It shows the applicant's name and buttons to open the report and to
send or resend it by email (or text, if the applicant consented to SMS).

## Application being reviewed / referred underwriting (RW100, RW105, RW110)

A "The application is being reviewed" screen (expect a decision in 1–2 business
days). Depending on the outcome, the agent either continues when a decision path
is available, sees a revised (capped) situation with a continue option, or is
told to start a new application.

## Multiple application inquiry (MI100)

Shown when several recent applications are detected. The agent lists each recent
application (estimated date, company, amount, status) and explains, in a required
free-text field, the reason for the number of applications and total coverage
sought. **Submit** advances to the decision step.

## Age-related offer screens (AU100, AU105, AU205)

These handle changes tied to the applicant's age. One cancels the application
because the applicant's age changed and they're no longer eligible; one explains
that the age changed since the offer was accepted and an updated offer is coming
(with a "View Updated Offer" action); and one notifies that the applicant has
been approved with a capped-amount note.

## Revised underwriting payment (PM105)

The payment screen used in the revised-underwriting flow. It first loads the
revised offer's payment quotes so the agent can confirm the updated coverage and
premium, then collects the same payment details and banking information as the
standard payment screen.
