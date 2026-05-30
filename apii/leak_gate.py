"""Fast residual-PII egress gate.

Before the proxy forwards an anonymized payload upstream, this answers a
single yes/no: does any raw PII shape remain? It is a deliberately
TIGHTER, broader-than-detection set of high-precision patterns scanned in
one linear pass — it trades some recall for speed and refuses to ship
anything that looks like raw PII. It deliberately also flags credential
and card shapes: even where those aren't tokenized, an egress gate should
refuse to ship them (defense in depth).

Our own placeholder tokens (PREFIX_HEX private tokens + balanced-mode
public tokens) are stripped before the scan so a tokenized field never
trips the gate.
"""

from __future__ import annotations

import regex

from apii.normalize import normalize_digits, scrub_invisible

# Tightly-scoped high-precision PII shapes. Order is documentary — a match
# of ANY pattern is a residual leak.
_LEAK_PATTERNS = (
    r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",  # email
    r"\b(?:SA|AE|QA|KW|BH|OM)\d{2}[A-Z0-9 \-]{15,30}\b",  # GCC IBAN shape
    r"(?:\+|00)?(?:966|971|974|965|973|968)[\s\-\.]?\d(?:[\s\-\.]?\d){6,10}",  # GCC intl phone
    r"\b0?5\d(?:[\s\-]?\d){7}\b",  # Saudi 05X mobile
    r"\b784[\- ]?\d{4}[\- ]?\d{7}[\- ]?\d\b",  # UAE Emirates ID
    r"\b(?:\d[ \-]?){13,19}\b",  # credit-card-length digit run
    r"(?i)\b(?:sk-[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|"
    r"(?:api[_\- ]?key|secret|token)\s*[:=]\s*[A-Za-z0-9_\-]{12,})\b",  # api keys / bearer
)

_LEAK_RE = [regex.compile(p) for p in _LEAK_PATTERNS]

# Strip our own tokens before scanning: private PREFIX_HEX + balanced-mode
# public tokens (BANK_…, PAYMENT_RAIL_…).
_PLACEHOLDER_STRIP_RE = regex.compile(
    r"\b(?:EMAIL|PHONE|IBAN|CR|TAX_ID|GOV_ID|PERSON|ORG|ADDRESS)_[A-F0-9]{10,32}\b"
    r"|\b(?:BANK|TELCO|CHANNEL|PAYMENT_RAIL|GOV)_[A-Z0-9_]+\b"
)


def has_residual_pii(text: str) -> bool:
    """True iff `text` still contains a raw PII shape after stripping our
    own placeholder tokens. One linear scan; returns on first match.

    The text is first scrubbed of zero-width / bidi-control / homoglyph
    chars and its Arabic-Indic / Persian digits are folded to ASCII — so an
    evasion-char-split or Arabic-digit-rendered raw value can't slip past
    the ASCII-literal egress patterns."""
    cleaned = normalize_digits(scrub_invisible(text))
    stripped = _PLACEHOLDER_STRIP_RE.sub("", cleaned)
    return any(rx.search(stripped) for rx in _LEAK_RE)
