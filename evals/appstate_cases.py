"""Cases for the live application-state projection (appstate.project.summarize).

These are DATA-LEVEL evals: each case is a synthetic memApp fed straight to the
projection, with substring predicates on the agent-facing summary. Deterministic
and offline — no platform, no model, no cost — so they run as a fast gate and pin
every rule we built:

  status translation (Pending-Issue dead-end), decision outcomes (incl. RUW and
  ineligible), offer-vs-quote, timeout expiry (future vs past), client
  notifications, "waiting on" stalls, and the hard safety invariants (no PII, no
  underwriting internals, no internal codes; wrong-product / empty → no summary).

Predicate keys match evals/run.py: all_of / any_of / none_of (case-insensitive);
`expect_none: True` asserts the projection declines to summarize (returns None).
"""
from __future__ import annotations


def app(**fields) -> dict:
    """A 511801 memApp with the given fields set."""
    return {"productId": "511801", **fields}


APPSTATE_CASES: list[dict] = [
    # ── status: the Pending-Issue dead-end, translated via the policy packet ──────
    {
        "name": "issued_with_packet",
        "memapp": app(arcidStatus="Issued", subStatus="Pending Issue", appDecisionCode=1,
                      uwConsentFlag=1, esignFlag=1, agentCertFlag="1", finalAdminIntegrationFlag=1,
                      finalCoverage=13000, finalPremiumMonthly=118, rateClassDescription="Level Preferred",
                      policyNo="3002618", policyPdfPacketReceivedDate="2026-08-05"),
        "all_of": ["status: issued", "policy packet is ready", "decision: approved",
                   "policy number: 3002618", "level preferred"],
        "none_of": ["pending issue"],
    },
    {
        "name": "pending_issue_no_packet",
        "memapp": app(arcidStatus="Pending Issue", subStatus="Pending Issue", appDecisionCode=1,
                      uwConsentFlag=1, esignFlag=1, agentCertFlag="1"),
        "all_of": ["not yet issued", "policy packet isn't available"],
        "none_of": ["pending issue"],
    },
    {
        # stuck*Timestamps are reminder-job markers, NOT live state — the
        # projection must ignore them and never emit a stuck-based "waiting on".
        "name": "pending_signature_stall",
        "memapp": app(arcidStatus="Pending signature(s)", subStatus="Pending signature(s)",
                      uwConsentFlag=1, stuckSignatureTimestamp="2026-08-20 10:00:00"),
        "all_of": ["status: pending signature"],
        "none_of": ["waiting on", "2026-08-20"],
    },
    # real NPW-* statuses embed the internal "NPW" term (and ID-check detail) —
    # they must be translated, never echoed.
    {
        "name": "status_npw_id_check",
        "memapp": app(arcidStatus="NPW-ID Check failure", subStatus="NPW-ID Check failure"),
        "all_of": ["verification step didn't pass"],
        "none_of": ["npw", "id check"],
    },
    {
        "name": "status_npw_timeout",
        "memapp": app(arcidStatus="NPW-Timeout"),
        "all_of": ["timed out"],
        "none_of": ["npw"],
    },
    {
        "name": "status_npw_not_eligible",
        "memapp": app(arcidStatus="NPW-Not ELigible"),
        "all_of": ["not able to proceed"],
        "none_of": ["npw"],
    },

    # ── decision outcomes (outcome only — never the reason) ──────────────────────
    {
        "name": "decision_approved",
        "memapp": app(arcidStatus="Offer", offerAcceptanceFlag="1", appDecisionCode=1),
        "all_of": ["decision: approved"],
    },
    {
        "name": "decision_declined_thirdparty",
        "memapp": app(arcidStatus="Declined", appDecisionCode=2),
        "all_of": ["decision: declined"],
        # never reveal WHICH decline (the reason) — only the outcome.
        "none_of": ["third party", "third-party", "mib", "milliman"],
    },
    {
        "name": "decision_declined_ko",
        "memapp": app(arcidStatus="Declined", appDecisionCode=4),
        "all_of": ["decision: declined"],
        "none_of": ["knock", "milliman", "mib"],
    },
    {
        # code 3 = MIB-Pend-Decline (a TERMINAL decline). Its arcidStatus may itself be
        # "MIB Pend" — the decline suppresses the Status line, so nothing confidential leaks.
        "name": "decision_declined_mib_pend",
        "memapp": app(arcidStatus="MIB Pend", subStatus="MIB Pend", appDecisionCode=3),
        "all_of": ["decision: declined"],
        "none_of": ["mib", "pend"],
    },
    {
        # A decline is OFF the issuance path — none of the progress / waiting / offer /
        # packet / policy-number lines should appear (they'd read as forward progress).
        "name": "declined_suppresses_issuance",
        "memapp": app(arcidStatus="Declined", subStatus="Declined", appDecisionCode=2,
                      uwConsentFlag=1, finalAdminIntegrationFlag=1, policyNo="3002646",
                      quoteCoverage=30000, consentEmailSent=1),
        "arc_id": "ARCF26233P678",
        "all_of": ["decision: declined"],
        "none_of": ["submitted to the carrier", "waiting on", "policy number",
                    "progress:", "quoted coverage", "notifications sent"],
    },
    {
        "name": "decision_ruw_pending",
        "memapp": app(arcidStatus="Referred", appDecisionCode=10),   # no ruwDecisionCode yet
        "all_of": ["under review by an underwriter"],
    },
    {
        "name": "decision_ruw_approved",
        "memapp": app(appDecisionCode=10, ruwDecisionCode=1),   # RUW → approved
        "all_of": ["decision: approved"],
    },
    {
        "name": "decision_ruw_declined",
        "memapp": app(appDecisionCode=10, ruwDecisionCode=2),   # RUW → declined
        "all_of": ["decision: declined"],
    },
    {
        "name": "decision_mib_reask",
        "memapp": app(appDecisionCode=11),   # decision-mapping only (no status set)
        "all_of": ["under review"],
        "none_of": ["mib"],
    },
    {
        "name": "decision_multiple_app_inquiry",
        "memapp": app(appDecisionCode=12),
        "all_of": ["under review"],
    },
    {
        "name": "decision_npw_expired",
        "memapp": app(arcidStatus="Offer", offerAcceptanceFlag="1", appDecisionCode=26),
        "all_of": ["offer expired"],
    },
    {
        "name": "decision_pending_99",
        "memapp": app(arcidStatus="Interview in Progress", appDecisionCode=99),
        "all_of": ["decision pending"],
    },
    {
        "name": "decision_unknown_code_safe",
        "memapp": app(arcidStatus="Interview in Progress", appDecisionCode=777),
        "all_of": ["a human can confirm"],     # never guess an outcome for an unknown code
        "none_of": ["approved", "declined"],
    },

    # ── milestone trail (journey questions) + face-amount unit pin ───────────────
    {
        "name": "milestones_journey",
        "memapp": app(arcidStatus="Issued", subStatus="Pending Issue", appDecisionCode=1,
                      uwConsentFlag=1, uwConsentTimestamp="2026-08-20 19:05:11",
                      esignFlag=1, esignTimestamp="2026-08-20 19:31:02",
                      agentCertFlag="1", agentCertTimestamp="2026-08-20 19:33:40",
                      finalAdminIntegrationFlag=1,
                      finalAdminIntegrationTimeStamp="2026-08-20 19:34:00",
                      uwDecisionDate="2026-08-20", policyIssueDate="2026-08-21",
                      policyPacketPdf="present", policyNo="3002999",
                      finalCoverage=21000, finalPremiumMonthly=81.21,
                      rateClassDescription="Level Preferred"),
        "all_of": ["milestones:", "consent 2026-08-20 19:05", "decision 2026-08-20",
                   "e-signed 2026-08-20 19:31", "agent certificate 2026-08-20 19:33",
                   "submitted to carrier 2026-08-20 19:34", "issued 2026-08-21",
                   "coverage 21000 (total face amount)"],
    },

    # ── offer vs quote ───────────────────────────────────────────────────────────
    {
        "name": "quote_stage_not_offer",
        "memapp": app(arcidStatus="Interview in Progress", quoteCoverage=30000),
        "all_of": ["quoted coverage: 30000", "decision pending"],
        "none_of": ["offer:", "monthly premium"],
    },
    {
        "name": "offer_stage",
        "memapp": app(arcidStatus="Offer", offerAcceptanceFlag="1", finalCoverage=25000,
                      finalPremiumMonthly=47.5, rateClassDescription="Standard"),
        "all_of": ["offer:", "coverage 25000", "monthly premium 47.5", "rate class standard"],
        "none_of": ["quoted coverage"],
    },

    # ── code 21 → ineligible for the product (off the issuance path) ─────────────
    {
        "name": "decision_ineligible_21",
        "memapp": app(arcidStatus="NPW-Not ELigible", appDecisionCode=21,
                      finalAdminIntegrationFlag=1, quoteCoverage=30000),
        "all_of": ["not eligible for this product"],
        "none_of": ["submitted to the carrier", "quoted coverage", "policy number", "npw"],
    },

    # ── timeout expiry: presence ≠ fired (compare to now) ────────────────────────
    {
        "name": "timeout_future_not_expired",
        "memapp": app(arcidStatus="Interview in Progress", npwTimeOutTimestamp="2099-01-01 00:00:00"),
        "none_of": ["expired"],
    },
    {
        "name": "timeout_past_expired",
        "memapp": app(arcidStatus="Offer", offerAcceptanceFlag="1",
                      npwOfferExpiredTimestamp="2000-01-01 00:00:00"),
        "all_of": ["window has expired", "re-started"],
    },

    # ── client notifications (channel decoded 1=email/2=SMS; raw code hidden) ────
    {
        "name": "notifications_sent",
        "memapp": app(arcidStatus="Interview in Progress", consentEmailSent=1,
                      appSignEmailSent=1, smsConsentFlag=1, notificationChannel="2"),
        "all_of": ["client notifications sent", "consent email", "signature email",
                   "channel: sms"],
        "none_of": ["notificationchannel", "channel: 2"],
    },
    {
        # unknown channel codes must stay hidden entirely
        "name": "notification_channel_unknown_hidden",
        "memapp": app(arcidStatus="Interview in Progress", consentEmailSent=1,
                      notificationChannel="7"),
        "all_of": ["consent email"],
        "none_of": ["channel"],
    },

    # ── hard safety invariants ───────────────────────────────────────────────────
    {
        "name": "no_pii_no_uw_leak",
        "memapp": app(
            arcidStatus="Issued", subStatus="Pending Issue", appDecisionCode=1,
            finalAdminIntegrationFlag=1, policyPdfPacketReceivedDate="2026-08-05",
            # PII + underwriting sentinels planted next to the safe fields
            applicantFirstName="ZZNAMESENTINEL", applicantEmail="victim@example.com",
            applicantTaxId="999-88-7777", bankAccountNo="12345678901234",
            MMDATA={"score": "ZZMILLIMAN"}, mibCodes=["ZZMIB1"], koRate="ZZKORATE",
            rateClass="31777", finalRate="ZZFINALRATE"),
        "all_of": ["status: issued"],
        "none_of": ["zznamesentinel", "victim@example.com", "999-88-7777", "12345678901234",
                    "zzmilliman", "zzmib1", "zzkorate", "31777", "zzfinalrate"],
    },
    {
        "name": "wrong_product_declines",
        "memapp": {"productId": "4127", "arcidStatus": "Issued"},
        "expect_none": True,
    },
    {
        "name": "empty_memapp_declines",
        "memapp": {},
        "expect_none": True,
    },
    {
        "name": "missing_productid_declines",
        "memapp": {"arcidStatus": "Issued"},
        "expect_none": True,
    },
]
