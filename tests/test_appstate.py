"""Safety + correctness checks for the live application-state projection.

Run:  python -m tests.test_appstate      (no pytest needed)

Proves the two guarantees that matter for surfacing live state to an agent:
  1. No applicant PII and no underwriting-internal value can reach the
     agent-facing summary.
  2. The safe operational status IS surfaced, in plain language.

Uses a synthetic 511801-shaped memApp with PII and underwriting sentinels
planted right next to the safe fields — the same adjacency that exists in a real
record — and asserts every sentinel is absent from the output while the
operational facts are present. No network, no live memApp.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from appstate import masking, project  # noqa: E402

# Values that must NEVER appear in the agent-facing output.
PII = {
    "applicantFirstName": "ZZNAMESENTINEL",
    "applicantLastName": "ZZLASTSENTINEL",
    "applicantEmail": "victim@example.com",
    "applicantTaxId": "999-88-7777",
    "applicantPhone": "(555) 123-4567",
    "bankAccountNo": "12345678901234",
    "bankRoutingNo": "021000021",
    "agentEmail": "agent@example.com",
    "identityKey": "ZZIDKEYSENTINEL",
    "clientConsentOtp": "838271",
    "otpCode": "112233",
}
UNDERWRITING = {
    "MMDATA": {"score": "ZZMILLIMANSENTINEL"},
    "mmRiskRate": "ZZMMRATE",
    "mibCodes": ["ZZMIB1", "ZZMIB2"],
    "koRate": "ZZKORATE",
    "finalRate": "ZZFINALRATE",
    "rateClass": "31777",          # numeric rate-class CODE — must not surface
    "bmiRateClass": "ZZBMI",
    "qaRate": "ZZQARATE",
    "impCodeUWDetails": {"x": "ZZIMPSENTINEL"},
}
SAFE = {
    "productId": "511801",
    "arcidStatus": "Issued",
    "subStatus": "Pending Issue",
    "appDecisionCode": 1,
    "uwConsentFlag": 1,
    "esignFlag": 1,
    "agentCertFlag": "1",
    "finalAdminIntegrationFlag": 1,
    "finalCoverage": 25000,
    "finalPremiumMonthly": 47.5,
    "rateClassDescription": "Standard",   # the LABEL is agent-facing (safe)
    "consentEmailSent": 1,
    "appSignEmailSent": 1,
    "notificationChannel": "2",           # a bare internal code — must NOT surface
    "appInitDate": "2026-08-04 13:07:50",
    "appExpiryDate": "2026-09-04",
    "policyNo": "3002359",
    "policyPdfPacketReceivedDate": "2026-08-05",
    "signedForms": {"app": "ZZFORMBLOB"},  # present pre-issue — must not alone imply a packet
}


def _memapp() -> dict:
    m: dict = {}
    m.update(UNDERWRITING)
    m.update(PII)
    m.update(SAFE)
    return m


def _sentinels() -> list[str]:
    out: list[str] = []
    for val in {**PII, **UNDERWRITING}.values():
        if isinstance(val, dict):
            out.extend(str(v) for v in val.values())
        elif isinstance(val, list):
            out.extend(str(v) for v in val)
        else:
            out.append(str(val))
    return out


def run() -> int:
    fails: list[str] = []
    out = project.summarize(_memapp(), "ARCF26216Z479")
    if not out:
        print("FAIL: no summary produced for a valid 511801 application")
        return 1

    for needle in _sentinels():
        if needle in out:
            fails.append(f"LEAK: sentinel {needle!r} appeared in the summary")

    for must in ("Issued", "the policy packet is ready", "Approved", "Standard",
                 "3002359", "Submitted to the carrier", "consent email"):
        if must not in out:
            fails.append(f"MISSING: expected {must!r} in the summary")
    # "Pending Issue" is a dead-end sub-status — translated via the packet, never echoed.
    if "Pending Issue" in out:
        fails.append("PENDING-ISSUE: dead-end 'Pending Issue' must not be surfaced")

    # The bare internal notificationChannel code must never surface.
    if "channel" in out.lower():
        fails.append("LEAK: notificationChannel surfaced ('channel' in output)")

    # "Pending Issue" WITHOUT a packet → 'Not yet issued', still never echoing it.
    no_packet = {"productId": "511801", "arcidStatus": "Pending Issue", "subStatus": "Pending Issue"}
    npout = project.summarize(no_packet, "ARCX") or ""
    if "Not yet issued" not in npout or "Pending Issue" in npout:
        fails.append("PENDING-ISSUE: no-packet case should read 'Not yet issued', never 'Pending Issue'")

    # Identical NON-pending statuses still collapse to one, not "X — X".
    dup = _memapp()
    dup["arcidStatus"] = dup["subStatus"] = "Issued"
    dout = project.summarize(dup, "ARCF26216Z479") or ""
    if "Issued — Issued" in dout:
        fails.append("DEDUPE: identical arcidStatus/subStatus were not collapsed")
    if "- Status: Issued" not in dout:
        fails.append("DEDUPE: collapsed status line missing")

    # Pre-offer (interview-stage) app: coverage on file but no premium / offer flag →
    # it's the applicant's QUOTE, not an offer, and must not be labelled "Offer".
    quote_stage = {"productId": "511801", "arcidStatus": "Interview in Progress",
                   "coverage": 30000}
    qout = project.summarize(quote_stage, "ARCF26231H677") or ""
    if "Quoted coverage: 30000" not in qout:
        fails.append("QUOTE: pre-offer coverage should read 'Quoted coverage'")
    if "Offer:" in qout:
        fails.append("QUOTE: a pre-offer app must not show an 'Offer:' line")

    # A timeout timestamp in the FUTURE is a deadline, not an expiry — no "expired".
    future = {"productId": "511801", "arcidStatus": "Interview in Progress",
              "quoteCoverage": 30000, "npwTimeOutTimestamp": "2099-01-01 00:00:00"}
    if "expired" in (project.summarize(future, "ARCF26231H677") or "").lower():
        fails.append("EXPIRY: a future timeout must NOT be reported as expired")

    # A timeout timestamp in the PAST is a real expiry — show the restart note.
    past = {"productId": "511801", "arcidStatus": "Offer", "offerAcceptanceFlag": "1",
            "npwOfferExpiredTimestamp": "2000-01-01 00:00:00"}
    if "needs to be re-started" not in (project.summarize(past, "ARCX") or ""):
        fails.append("EXPIRY: a past timeout should show the restart note")

    foreign = _memapp()
    foreign["productId"] = "4127"
    if project.summarize(foreign, "ARCD26196s109") is not None:
        fails.append("PRODUCT GUARD: a foreign productId should return None")

    if project.summarize({}, "ARCX26216Z479") is not None:
        fails.append("EMPTY: an empty memApp should return None")

    for probe, why in [("reach me at a@b.com now", "email"),
                       ("ssn 123-45-6789 here", "ssn"),
                       ("call (555) 987-6543", "phone"),
                       ("doc https://blob.core.windows.net/x.pdf", "url"),
                       ("acct 12345678901234 ok", "long-digits")]:
        if probe == masking.scrub(probe):
            fails.append(f"SCRUB: failed to mask {why} in {probe!r}")

    print(out)
    print("\n" + "=" * 60)
    if fails:
        print("FAIL:\n  " + "\n  ".join(fails))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
