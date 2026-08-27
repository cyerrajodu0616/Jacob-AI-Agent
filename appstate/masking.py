"""Defense-in-depth scrub for any string surfaced to the agent.

The projection in project.py is a positive ALLOWLIST: only known-safe operational
fields are ever read. This is the second net. Every string that survives into the
agent-facing summary is scrubbed of anything that still looks like PII (email /
SSN / phone / long digit runs) or a document link, and capped in length. So even
if an allowlisted status field one day carried a name, an email, or a URL, it
can't reach the agent verbatim. Model-agnostic; imports nothing but `re`.
"""
from __future__ import annotations

import re

_MASK = "[hidden]"
_MAXLEN = 200

_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,255}\.[a-z]{2,24}", re.I)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE = re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_LONG_DIGITS = re.compile(r"\b\d{9,19}\b")          # unformatted SSN / phone / account / card
_URL = re.compile(
    r"\b(?:https?|s3|gs|ftp|ftps|sftp|abfss|azure|wasb|blob|data)://\S+"
    r"|\bwww\.\S+"
    r"|\S+\.(?:pdf|docx?|tiff?|png|jpe?g)(?=\b|$|\?)",
    re.I,
)


def scrub(value):
    """Scrub a scalar we intend to surface.

    Non-strings pass through unchanged (a number, bool, or None carries no
    free-text PII, and operational amounts/flags must stay readable). A string is
    stripped of link/email/SSN/phone/long-digit patterns and length-capped.
    """
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return s
    s = _URL.sub(_MASK, s)
    s = _EMAIL.sub(_MASK, s)
    s = _SSN.sub(_MASK, s)
    s = _PHONE.sub(_MASK, s)
    s = _LONG_DIGITS.sub(_MASK, s)
    if len(s) > _MAXLEN:
        s = s[:_MAXLEN] + "…"
    return s
