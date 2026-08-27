# Application Journey — NewBridge Final Expense (511801)

## The normal application flow

A standard application moves through these steps in order. The eApp controls
navigation; some steps branch or repeat based on the applicant and underwriting,
but the typical path is:

1. **Quote input / lead form (QO100)** — the applicant's basic details to start.
2. **Pre-application assessment (MS100)** — the brief assessment interstitial
   (good fit / not likely eligible / neutral proceed).
3. **Quote (QO105)** — the quote builder: coverage and premium (quote by either;
   the quote engine converts coverage ⇄ premium).
4. **Confirm eligibility (QO110)** — the eligibility checklist the agent
   confirms with the applicant. When Next is clicked, agent verification runs
   behind the scenes.
5. **Before You Begin — questions for producer (QO115) and security warning
   (QO120)** — the producer's controlled-business questions, then the security
   acknowledgment. After this the agent starts the application and the
   interview begins.
6. **Identity & interview (IV100 through IV120)** — applicant identity plus the
   interview/underwriting questions.
7. **Consent (CO100)** — the agent sends the applicant a consent request by
   email or text. The applicant opens the link and gives their consent on their
   own screen. The application continues once consent is completed.
8. **Beneficiaries (BE100)** — name and set up the beneficiaries.
9. **Decision wait (DW100)** — the application is processed for an
   instant decision.
10. **Offer (OF100)** — the decision/offer is presented for review.
11. **Payment (PM100)** — payment details are collected.
12. **Signing (SA100, SC100, SN100)** — the agent sends the applicant a review-
   and-sign request by email or text. The applicant opens the link, reviews the
   application, and e-signs on their own screen. The application continues once
   signing is completed.
13. **Producer certificate (AC100)** — the producing agent's certification.
14. **Congratulations (CG100)** — the application is complete and submitted.

After CG100 the application is submitted; a completed application typically sits
in a "Pending Issue" state while final processing happens.

## Steps where the applicant acts on their own screen

Two steps hand off to the applicant. At each one, the agent sends a link and the
applicant completes their part separately before the agent can continue:

- **Consent (CO100)** — the agent triggers a consent request (email or SMS); the
  applicant opens it and consents.
- **Signing (SA100/SC100/SN100)** — the agent triggers a review-and-sign request
  (email or SMS); the applicant opens it, reviews the application, and e-signs.

If the applicant hasn't received the email or text, re-check the email/phone on
that step and resend, and have the applicant check spam. The application will not
advance past these steps until the applicant completes their part. After signing
is done, the agent completes the producer certificate (AC100) and reaches
Congratulations (CG100).

## Pausing and resuming an application

- Interview answers save as they are entered — pausing mid-application does not
  lose them.
- To resume an in-progress application, start from the applicant's identity:
  when the person already has an application in progress, the agent is routed
  to resume it.
- An application times out 30 days after it was started; within that window it
  can be picked back up.

## What an agent is doing at each stage

- **Quote steps (QO…)**: entering coverage amount and product selections to
  produce the quote.
- **Identity & interview (IV…)**: confirming the applicant's identity and
  answering the health/lifestyle interview questions that feed underwriting.
- **Consent (CO100)**: the applicant agrees to the required disclosures before
  underwriting proceeds.
- **Beneficiaries (BE100)**: adding beneficiaries and their relationship to the
  insured.
- **Decision wait / Offer (DW100 → OF100)**: the platform returns an instant
  decision, then the offer is shown for acceptance.
- **Payment (PM100)**: setting up how premiums will be paid.
- **Signing (SA/SC/SN…)**: the agent sends the applicant a request to review and
  e-sign; the applicant completes it on their own screen.
- **Producer certificate (AC100)**: after the applicant has signed, the agent
  certifies the application.

## Notes for agents

- This is the standard path. The exact screens and their order can vary by
  applicant and by the underwriting outcome — the eApp decides what comes next.
- Two steps depend on the applicant: consent (CO100) and signing
  (SA100/SC100/SN100). The application pauses at each until the applicant opens
  the emailed/texted link and completes their part.
- If an application appears stuck on the decision-wait step, or the flow will not
  advance past a step showing a warning, that's a support/underwriting matter —
  a human should follow up.
