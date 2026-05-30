"""Reversible PII tokenization.

The product loop: detect PII → replace each span with a deterministic,
reversible token → (send the tokenized text to an LLM) → restore the
original values on the way back from the vault.

Token scheme:

    HMAC-SHA256(secret; tenant ⊥ [session] ⊥ kind_prefix ⊥ normalized)
    token = f"{kind_prefix}_{HEX_UPPER(digest[:8])}"      # 16 hex chars

where ⊥ is the 0x1F unit separator and `normalized` is
`normalize_for_kind(kind, value)`. Properties:
  - Deterministic: the same (tenant, session, kind, normalized-value)
    always yields the same token, so a repeated entity collapses to one
    token and cross-message references stay linkable.
  - Session-scoped: with a session set, the same value gets a stable
    token within the session but a DIFFERENT token across sessions
    (cross-conversation unlinkability). With no session the HMAC input is
    byte-identical to a session-unaware build.
  - Irreversible without the vault: the token reveals only the kind; the
    value lives only in the local vault map.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional

import msgspec

from apii.normalize import normalize_for_kind, scrub_invisible
from apii.pipeline import Pipeline
from apii.policy import AnonymizationPolicy
from apii.replacer import replace_longest_first, replace_spans
from apii.types import Detection, EntityKind

# 0x1F unit separator — the derive_token field delimiter.
_US = b"\x1f"

# Max edit distance for fuzzy token restore.
_MAX_FUZZY_DISTANCE = 2


def _levenshtein_bounded(a: str, b: str, max_dist: int) -> int | None:
    """Bounded Wagner–Fischer over chars; None if distance > max_dist."""
    if abs(len(a) - len(b)) > max_dist:
        return None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        curr = [i] + [0] * len(b)
        row_min = curr[0]
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min > max_dist:
            return None
        prev = curr
    d = prev[len(b)]
    return d if d <= max_dist else None


def _best_fuzzy_match(needle: str, haystack: list[str], max_dist: int) -> str | None:
    """Closest haystack token within max_dist, or None."""
    best = None
    best_d = max_dist + 1
    for cand in haystack:
        d = _levenshtein_bounded(needle, cand, max_dist)
        if d is not None and d < best_d:
            best_d, best = d, cand
    return best


class EntityRecord(msgspec.Struct, frozen=True):
    """One vault entry: the token, its kind, and both value forms."""

    kind: EntityKind
    token: str
    value: str
    normalized: str


class AnonymizationReport(msgspec.Struct):
    text: str
    detections: list[Detection]
    records: list[EntityRecord]


class DeanonymizationReport(msgspec.Struct):
    text: str
    restored: list[str]  # canonical tokens restored
    unrestored_tokens: list[str]


class Anonymizer:
    """Stateful reversible tokenizer over one detection pipeline + vault.

    Construct with a secret + tenant (+ optional session). The vault
    (token↔record maps) grows as text is anonymized; pass it to
    `deanonymize` (same instance, or rebuilt via `from_records`) to
    restore.
    """

    def __init__(
        self,
        secret: bytes | str,
        tenant: str,
        *,
        session: Optional[str] = None,
        pipeline: Optional[Pipeline] = None,
        policy: Optional[AnonymizationPolicy] = None,
    ) -> None:
        self._secret = secret.encode() if isinstance(secret, str) else bytes(secret)
        self._tenant = tenant
        self._session = session
        self._policy = policy if policy is not None else AnonymizationPolicy.strict()
        # Detection authority. Defaults to the product pipeline (regex +
        # NER when available). Injectable for tests / regex-only use.
        if pipeline is None:
            from apii import default_pipeline

            pipeline = default_pipeline()
        self._pipeline = pipeline
        self._token_to_record: dict[str, EntityRecord] = {}
        # Keyed by (session, kind, normalized) — session None on the
        # session-unaware path so loaded records stay portable.
        self._norm_to_token: dict[tuple[Optional[str], EntityKind, str], str] = {}

    # ── construction / vault io ──

    @classmethod
    def from_records(
        cls,
        secret: bytes | str,
        tenant: str,
        records: list[EntityRecord],
        *,
        session: Optional[str] = None,
        pipeline: Optional[Pipeline] = None,
        policy: Optional[AnonymizationPolicy] = None,
    ) -> "Anonymizer":
        a = cls(secret, tenant, session=session, pipeline=pipeline, policy=policy)
        for r in records:
            a._norm_to_token[(None, r.kind, r.normalized)] = r.token
            a._token_to_record[r.token] = r
        return a

    def records(self) -> list[EntityRecord]:
        return sorted(self._token_to_record.values(), key=lambda r: r.token)

    def set_session(self, session: Optional[str]) -> None:
        self._session = session

    @property
    def session(self) -> Optional[str]:
        return self._session

    # ── token derivation ──

    def _derive_token(self, kind: EntityKind, normalized: str) -> str:
        mac = hmac.new(self._secret, digestmod=hashlib.sha256)
        mac.update(self._tenant.encode())
        mac.update(_US)
        if self._session is not None:
            mac.update(b"session")
            mac.update(_US)
            mac.update(self._session.encode())
            mac.update(_US)
        prefix = kind.token_prefix
        mac.update(prefix.encode())
        mac.update(_US)
        mac.update(normalized.encode())
        suffix = mac.digest()[:8].hex().upper()
        return f"{prefix}_{suffix}"

    def token_for_value(self, kind: EntityKind, value: str) -> str:
        """Token for an explicit (kind, value), registering it in the vault."""
        normalized = normalize_for_kind(kind, value)
        key = (self._session, kind, normalized)
        existing = self._norm_to_token.get(key)
        if existing is not None:
            return existing
        token = self._derive_token(kind, normalized)
        record = EntityRecord(kind=kind, token=token, value=value, normalized=normalized)
        self._norm_to_token[key] = token
        self._token_to_record[token] = record
        return token

    # ── anonymize / deanonymize ──

    def detect(self, text: str) -> list[Detection]:
        # Scrub zero-width / bidi-control chars + fold homoglyphs BEFORE
        # detection. Without this, a single invisible char inside a value
        # defeats every recognizer regex — a real PII-leak class the gateway
        # must close.
        return self._pipeline.detect(scrub_invisible(text))

    def anonymize(self, text: str) -> AnonymizationReport:
        # Scrub first (see detect). Detection + replacement then operate in
        # the scrubbed coordinate space, so the output is the scrubbed text
        # with tokens spliced in — evasion chars never survive into the
        # redacted output.
        text = scrub_invisible(text)
        detections = self._pipeline.detect(text)
        # Audit mode: detect only — report what was found, mutate nothing.
        if self._policy.is_audit():
            return AnonymizationReport(text=text, detections=detections, records=[])

        replacements: list[tuple[int, int, str]] = []
        changed: dict[str, EntityRecord] = {}
        for d in detections:
            # redact_kinds gate: kinds outside the set stay in the output
            # text (still reported via `detections`).
            if not self._policy.should_redact(d.kind):
                continue
            value = text[d.start : d.end]
            # Balanced mode: an allowed public term passes through verbatim.
            passthrough = self._policy.replacement_for(d.kind, value)
            if passthrough is not None:
                continue  # leave the value in place
            token = self.token_for_value(d.kind, value)
            replacements.append((d.start, d.end, token))
            rec = self._token_to_record.get(token)
            if rec is not None:
                changed[token] = rec
        output = replace_spans(text, replacements)
        return AnonymizationReport(
            text=output,
            detections=detections,
            records=sorted(changed.values(), key=lambda r: r.token),
        )

    def deanonymize(self, text: str) -> str:
        return self.deanonymize_with_report(text).text

    def deanonymize_with_report(self, text: str) -> DeanonymizationReport:
        pairs = [(r.token, r.value) for r in self._token_to_record.values()]
        output, hits = replace_longest_first(text, pairs)
        restored = [needle for needle, _ in hits]

        # Fuzzy fallback: an LLM may mangle a token's hex suffix (flip/drop a
        # char). For each leftover PREFIX_HEX token with no exact vault entry,
        # find the closest vault token within Levenshtein distance 2 and
        # restore it.
        vault_tokens = list(self._token_to_record.keys())
        if vault_tokens:
            def _fuzzy(m) -> str:
                tok = m.group()
                if tok in self._token_to_record:
                    return tok  # exact (already handled, but be safe)
                best = _best_fuzzy_match(tok, vault_tokens, _MAX_FUZZY_DISTANCE)
                if best is None:
                    return tok
                restored.append(best)
                return self._token_to_record[best].value

            output = _PRIVATE_TOKEN_RE.sub(_fuzzy, output)

        unrestored = sorted(
            {
                m.group()
                for m in _PRIVATE_TOKEN_RE.finditer(output)
                if m.group() not in self._token_to_record
            }
        )
        return DeanonymizationReport(
            text=output, restored=sorted(set(restored)), unrestored_tokens=unrestored
        )


# Canonical bare-token shape `PREFIX_<10-32 hex>`, word-bounded, over the
# in-scope prefixes.
import regex as _regex  # noqa: E402

_PREFIXES = "|".join(
    sorted({k.token_prefix for k in EntityKind}, key=len, reverse=True)
)
_PRIVATE_TOKEN_RE = _regex.compile(rf"\b(?:{_PREFIXES})_[A-F0-9]{{10,32}}\b")
