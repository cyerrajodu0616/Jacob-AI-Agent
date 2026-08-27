"""Project a live memApp into a small, agent-safe status summary.

This is the STRICTER, agent-facing counterpart to an engineer's memApp view. It
is a positive ALLOWLIST: only a hand-picked set of operational fields is ever
read, each mapped to plain language. Everything else in the ~380-field memApp —
all applicant PII, every underwriting mechanic (MIB / Milliman / risk / rate
math), and every internal code — is simply never touched. Each string that does
get surfaced then passes through masking.scrub() as defense in depth.

Grounded in the real 511801 memApp shape and the arc-core code tables:
  • Decision codes: 1 Approved · 2/3/4 decline · 10 RUW · 11/12 MIB re-ask ·
    26 NPW · 99 pre-decision. We surface the OUTCOME only; the distinction
    between decline reasons is the confidential "why" and is collapsed away.
  • For 511801, progress is the flag chain (uwConsentFlag → esignFlag →
    agentCert → finalAdminIntegration), NOT journeyStatus (unreliable here).
  • arcidStatus / subStatus are the canonical self-describing status labels.
"""
from __future__ import annotations

from datetime import datetime

import config
from . import masking

# appDecisionCode → agent-facing OUTCOME only (logic in _decision). Every decline
# subtype (knock-out / MIB / third-party / AIF / ID-check) collapses to "Declined" —
# WHICH one is the confidential reason and must never be exposed.

# 511801 progress = this ordered flag chain (per arc-core; journeyStatus is
# explicitly unreliable for this product, so we do not read it).
_PROGRESS = [
    # Per SME (2026-08-23): CO100 consent sets uwConsentFlag + uwConsentTimeStamp;
    # SN100 e-sign sets eSignFlag + eSignTimestamp (capital S — the lowercase
    # spelling kept as a fallback); AC100 sets agentCertFlag + agentCertTimestamp.
    # Spellings verified against a live 387-key prod record (2026-08-23):
    # uwConsentTimestamp, esignFlag/esignTimestamp, agentCertTimestamp,
    # finalAdminIntegrationTimeStamp (capital S). SME-quoted variants kept too.
    ("UW consent given", ("uwConsentFlag", "uwConsentTimestamp", "uwConsentTimeStamp")),
    ("Application e-signed", ("eSignFlag", "esignFlag", "esignTimestamp",
                              "eSignTimestamp", "eSignCompletedFlag")),
    ("Agent certificate completed", ("agentCertFlag", "agentCertTimestamp")),
    # Set when the policy is submitted to CG (the A103 submission at the
    # congratulations screen).
    ("Submitted to the carrier", ("finalAdminIntegrationFlag",
                                  "finalAdminIntegrationTimeStamp",
                                  "finalAdminIntegrationTimestamp")),
]

# stuck*Timestamp fields are IGNORED entirely (SME, 2026-08-23): they are
# reminder-job markers (when a stuck-nudge fired), not live state — they can
# persist after the step completes, so reading them as "currently waiting on X"
# misreports progressed applications.

# Client notifications actually sent.
_NOTIF = [
    ("consent email", "consentEmailSent"),
    ("signature email", "appSignEmailSent"),
    ("consent SMS", "smsConsentFlag"),
]

_FALSY = {None, "", "0", 0, False, "false", "False", "None", "none", "null", "NULL"}


def _has(memapp: dict, *keys: str) -> bool:
    """True if any of `keys` holds a meaningful (non-falsy, non-empty) value."""
    for key in keys:
        value = memapp.get(key)
        if isinstance(value, (dict, list)):
            if value:
                return True
            continue
        if value not in _FALSY:
            return True
    return False


def _first(memapp: dict, *keys: str):
    """The first meaningful scalar among `keys` (skips containers), else None."""
    for key in keys:
        value = memapp.get(key)
        if isinstance(value, (dict, list)):
            continue
        if value not in _FALSY:
            return value
    return None


def _expired(ts) -> bool:
    """True only if a 'YYYY-MM-DD[ HH:MM:SS]' timestamp is already in the past.

    Both npw* fields are SCHEDULED deadlines, never fired-events (SME 2026-08-23):
    npwTimeOutTimestamp is set to appInitDate+30d when the interview starts and is
    CLEARED once a decision lands; npwOfferExpiredTimestamp is set to +30d when the
    offer is approved (the payment window). So presence must never be read as
    "expired" — only a deadline already in the past means the window lapsed.
    """
    ts = (str(ts) if ts is not None else "").strip()
    if not ts:
        return False
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts[:19], fmt) < datetime.now()
        except ValueError:
            continue
    return False


def _decision(memapp: dict) -> str:
    """Agent-safe outcome, per the 511801 decision-code logic:

    1 approved · 2/3/4 declined (3 = MIB-pend, 4 = KO/AIF/ID-check — all just
    "Declined" to the agent) · 10 = in referred underwriting: the real outcome is
    ruwDecisionCode (1 approve / 2·3·4 decline / else still under review) · 11 (MIB
    reask) & 12 (multiple-application inquiry) → "Under review" · 26 offer expired ·
    99 / blank pending · anything else → unclear (never guess an outcome).
    """
    raw = memapp.get("appDecisionCode")
    if isinstance(raw, (dict, list)) or raw is None:
        return "Decision pending"
    code = str(raw).strip()
    if code == "1":
        return "Approved"
    if code in ("2", "3", "4"):
        return "Declined"
    if code == "21":
        return "Not eligible for this product"
    if code == "10":                          # in RUW — the outcome is ruwDecisionCode
        ruw = str(memapp.get("ruwDecisionCode") or "").strip()
        if ruw == "1":
            return "Approved"
        if ruw in ("2", "3", "4"):
            return "Declined"
        return "Under review by an underwriter"
    if code in ("11", "12"):
        return "Under review"
    if code == "26":
        return "Offer expired (no payment within the required window)"
    if code in ("99", ""):
        return "Decision pending"
    return "Unclear — a human can confirm"


# Some real arcidStatus/subStatus values embed internal terms — "NPW-…" (not
# proceeding), MIB, vendor names. Those are confidential, so translate them to
# agent-safe language instead of echoing the raw label.
def _safe_status(s: str) -> str:
    low = s.strip().lower()
    if "npw" in low:                        # "not proceeding" — keep the reason high-level
        if "timeout" in low:
            return "The application timed out and can't proceed"
        if "id check" in low:
            return "Stopped — a verification step didn't pass"
        return "Not able to proceed — a human can confirm the details"
    if any(tok in low for tok in ("mib", "milliman", "sherlock")):
        return "Under review — a human can confirm the details"
    return s


def summarize(memapp: dict, arc_id: str) -> str | None:
    """Plain-language live status for one application.

    Returns the labelled summary text, or None if this isn't a record this
    product should interpret (wrong product, or no usable record).
    """
    if not isinstance(memapp, dict) or not memapp:
        return None
    if str(memapp.get("productId") or "").strip() != config.PRODUCT:
        return None  # not a 511801 application — Jacob won't interpret it

    lines = [f"Live status for application {masking.scrub(arc_id)} "
             f"({config.PRODUCT_NAME}):"]

    # A declined or ineligible application is off the issuance path — its progress /
    # waiting / offer / packet / policy-number fields would all read as forward
    # progress and mislead; for those we show only the outcome and timeline.
    decision = _decision(memapp)
    off_track = decision in ("Declined", "Not eligible for this product")

    # Status. "Pending Issue" is a DEAD-END sub-status that never flips to "Issued" —
    # the policy packet is the real completion signal — so translate it via the packet
    # instead of echoing it. Otherwise show arcidStatus [— subStatus], de-duplicated.
    # Per SME: after finalAdminIntegrationFlag (submission), policyPacketPdf
    # arriving is what marks the REAL "Issued" — there is no trustworthy
    # "Issued" status label to wait for.
    packet = _has(memapp, "policyPacketPdf", "policyPdfPacketReceivedDate")
    arcid_status = str(_first(memapp, "arcidStatus") or "")
    sub_status = str(_first(memapp, "subStatus") or "")
    dead_end_pending = "pending issue" in f"{arcid_status} {sub_status}".lower()
    if not off_track:                      # for a decline the Decision line carries it
        if dead_end_pending:
            lines.append("- Status: Issued — the policy packet is ready" if packet
                         else "- Status: Not yet issued — the policy packet isn't available yet")
        else:
            parts: list[str] = []
            for v in (_safe_status(arcid_status), _safe_status(sub_status)):
                sv = masking.scrub(v.strip())
                if sv and sv not in parts:   # arcidStatus and subStatus are often identical
                    parts.append(sv)
            if parts:
                lines.append("- Status: " + " — ".join(parts))

    lines.append(f"- Decision: {decision}")

    if not off_track:
        done = [label for label, keys in _PROGRESS if _has(memapp, *keys)]
        lines.append("- Progress: " + ("; ".join(done) if done
                     else "still in the early steps (before UW consent)"))

        # WHEN each step happened — the agent-safe milestone trail, so "walk me
        # through what happened on this application" gets a real chronology.
        # Dates/timestamps only; the decision DATE is operational (the why stays
        # hidden). Only present fields appear, scrubbed.
        milestones = []
        for label, keys in (
            ("consent", ("uwConsentTimestamp", "uwConsentTimeStamp")),
            ("decision", ("uwDecisionDate", "uwOriginalDecisionDate")),
            ("e-signed", ("esignTimestamp", "eSignTimestamp")),
            ("agent certificate", ("agentCertTimestamp",)),
            ("submitted to carrier", ("finalAdminIntegrationTimeStamp",
                                      "finalAdminIntegrationTimestamp")),
            ("issued", ("policyIssueDate",)),
        ):
            val = _first(memapp, *keys)
            if val is not None:
                milestones.append(f"{label} {masking.scrub(str(val))}")
        if milestones:
            lines.append("- Milestones: " + "; ".join(milestones))

        # A submitted/issued app isn't waiting on anything. (No per-step
        # "waiting on" is derived otherwise — stuck timestamps are ignored, see
        # above; arcidStatus/subStatus carry where the application sits.)
        issued = _has(memapp, "finalAdminIntegrationFlag") or \
            "issued" in str(memapp.get("arcidStatus") or "").lower()
        if issued:
            lines.append("- Waiting on: nothing outstanding — it's been submitted to the carrier")

        # Offer vs quote. A real OFFER has a decided premium (or an offer-acceptance
        # flag); before that, coverage on file is just the applicant's QUOTE selection.
        # Values are the application's own live figures — read, never computed.
        coverage = _first(memapp, "finalCoverage", "coverage", "quoteCoverage")
        premium = _first(memapp, "finalPremiumMonthly", "premiumMonthly", "offerPremium")
        rateclass = _first(memapp, "rateClassDescription")   # the LABEL, never the numeric code
        if premium is not None or _has(memapp, "offerAcceptanceFlag"):
            offer = []
            if coverage is not None:
                # "(total face amount)" pins the unit — a bare number next to a
                # monthly premium has been misread as "coverage $X/month".
                offer.append(f"coverage {coverage} (total face amount)")
            if premium is not None:
                offer.append(f"monthly premium {premium}")
            if rateclass:
                offer.append(f"rate class {masking.scrub(str(rateclass))}")
            if offer:
                lines.append("- Offer: " + "; ".join(offer))
        elif coverage is not None:
            lines.append(f"- Quoted coverage: {coverage}")

        sent = [label for label, key in _NOTIF if _has(memapp, key)]
        if sent:
            lines.append("- Client notifications sent: " + ", ".join(sent))
        # notificationChannel decodes 1 → email, 2 → SMS (SME 2026-08-23). Only
        # the decoded word is surfaced — never the raw code; unknown codes stay hidden.
        channel = {"1": "email", "2": "SMS"}.get(str(memapp.get("notificationChannel") or "").strip())
        if channel:
            lines.append(f"- Client notification channel: {channel}")

    # Per SME: arcDate is when the application (arcId) was started; appInitDate
    # is specifically when the INTERVIEW was started (post-quote/acknowledge).
    # appExpiryDate mirrors the +30-day deadline mechanics and (per SME, likely
    # but not certain) REFRESHES to +30 when the offer is approved — so treat it
    # as "the current deadline", not "interview start + 30" forever.
    timeline = []
    arc_started = _first(memapp, "ArcDate", "arcDate")   # live key is ArcDate
    interview_started = _first(memapp, "appInitDate")
    expires = _first(memapp, "appExpiryDate")
    if arc_started:
        timeline.append(f"started {masking.scrub(str(arc_started))}")
    if interview_started:
        timeline.append(f"interview started {masking.scrub(str(interview_started))}")
    if expires:
        timeline.append(f"expires {masking.scrub(str(expires))}")
    if timeline:
        lines.append("- Timeline: " + "; ".join(timeline))
    # Only when a timeout has ACTUALLY passed — not just because the field exists.
    npw = _first(memapp, "npwOfferExpiredTimestamp", "npwTimeOutTimestamp")
    if not off_track and _expired(npw):
        lines.append("- Note: this application's window has expired — it likely "
                     "needs to be re-started")

    if not off_track:
        # Only when the finished policy packet actually exists (not signedForms), and
        # not already spoken to by the dead-end "Pending Issue" translation above.
        if packet and not dead_end_pending:
            lines.append("- Documents: policy packet available")
        policy_no = _first(memapp, "policyNo", "policyNumber")
        if policy_no:
            lines.append(f"- Policy number: {masking.scrub(str(policy_no))}")
        effective = _first(memapp, "policyEffectiveDate")
        if effective:
            lines.append(f"- Policy effective date: {masking.scrub(str(effective))}")

    lines.append(
        "\nWithheld (underwriting-internal — do not infer, state, or hint at these): "
        "the reason behind any decision or rate, health/risk details, vendor or "
        "identity checks, and any internal codes. Relay only the plain status above."
    )
    return "\n".join(lines)
