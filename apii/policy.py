"""Anonymization policy — strict / balanced / audit modes + redact-kinds.

  - **strict** (default): every detected PII span is replaced with an
    opaque reversible token (PERSON_…, IBAN_…).
  - **audit**: detect only — nothing is replaced; the report lists what
    was found so an operator can review without mutating the text.
  - **balanced**: like strict, but spans whose value matches an
    operator-supplied "allowed public term" pass through verbatim (e.g.
    a bank/utility name the operator deems non-sensitive in their
    context). Matching is Arabic-normalized + token-sequence based, so
    "مصرف الراجحي" / "Al Rajhi Bank" match their allowlist entries.

Balanced mode does not ship a hardcoded list of Saudi banks/telcos/
payment-rails mapped to semantic tokens (BANK_ALRAJHI, TELCO_STC,
PAYMENT_RAIL_SADAD): a fixed organization-name list is exactly what apii
avoids. Operators get the same effect declaratively via
`with_allowed_public_terms`.

`redact_kinds` narrows redaction to a subset of kinds — detections of
other kinds are still reported but left in the output text. An empty set
collapses to "redact everything" (a guard so an accidental empty config
never silently disables masking; use mode=audit to detect-without-redact).
"""

from __future__ import annotations

import enum

from apii.normalize import normalize_arabic
from apii.types import Detection, EntityKind


class AnonymizationMode(enum.Enum):
    STRICT = "strict"
    BALANCED = "balanced"
    AUDIT = "audit"

    @classmethod
    def parse(cls, value: str) -> "AnonymizationMode":
        v = value.strip().lower()
        for m in cls:
            if m.value == v:
                return m
        raise ValueError(
            f"unknown policy mode {value!r}; expected strict, balanced, or audit"
        )


def _public_tokens(value: str) -> list[str]:
    """Arabic-normalized, uppercased token list. ASCII alnum uppercased;
    Arabic chars kept; other chars split tokens."""
    out: list[str] = []
    cur: list[str] = []
    for ch in normalize_arabic(value):
        if ch.isascii() and ch.isalnum():
            cur.append(ch.upper())
        elif 0x0600 <= ord(ch) <= 0x06FF:
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _public_key(value: str) -> str:
    return " ".join(_public_tokens(value))


class AnonymizationPolicy:
    """Mode + allowlist + redact-kinds. Immutable-ish; builder methods
    return a new policy."""

    def __init__(
        self,
        mode: AnonymizationMode = AnonymizationMode.STRICT,
        allow_public_terms: frozenset[str] = frozenset(),
        redact_kinds: frozenset[EntityKind] | None = None,
    ) -> None:
        self.mode = mode
        self._allow = allow_public_terms
        self._redact_kinds = redact_kinds

    # ── constructors ──
    @classmethod
    def strict(cls) -> "AnonymizationPolicy":
        return cls(AnonymizationMode.STRICT)

    @classmethod
    def balanced(cls) -> "AnonymizationPolicy":
        return cls(AnonymizationMode.BALANCED)

    @classmethod
    def audit(cls) -> "AnonymizationPolicy":
        return cls(AnonymizationMode.AUDIT)

    # ── builders ──
    def with_allowed_public_terms(self, terms) -> "AnonymizationPolicy":
        keys = frozenset(k for k in (_public_key(t) for t in terms) if k)
        return AnonymizationPolicy(self.mode, keys, self._redact_kinds)

    def with_redact_kinds(self, kinds) -> "AnonymizationPolicy":
        s = frozenset(kinds)
        # Empty set collapses to None (redact everything) — never silently
        # disable masking via an empty config.
        return AnonymizationPolicy(self.mode, self._allow, s or None)

    # ── queries ──
    def is_audit(self) -> bool:
        return self.mode is AnonymizationMode.AUDIT

    def should_redact(self, kind: EntityKind) -> bool:
        if self._redact_kinds is None:
            return True
        return kind in self._redact_kinds

    def replacement_for(self, kind: EntityKind, value: str) -> str | None:
        """In balanced mode, return the value VERBATIM if it matches an
        allowed public term (so it passes through unredacted). Otherwise
        None → the caller falls back to a vault token. Strict/audit always
        return None here."""
        if self.mode is not AnonymizationMode.BALANCED:
            return None
        if _public_key(value) in self._allow:
            return value
        return None

    def semantic_replacement(self, detection: Detection) -> str | None:
        return self.replacement_for(detection.kind, detection.text)
