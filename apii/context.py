"""Context-aware confidence boosting.

Presidio-style: a detection is more trustworthy when domain context
words sit just before it ("IBAN SA03…" vs a bare SA03… string). For each
detection we scan the few preceding word tokens against a per-kind
context-word set and, on a hit, raise the confidence and record a
ContextBoostExplanation.

Placement: this runs LAST, after overlap resolution, so it never changes
WHICH spans are detected — only the confidence of spans that already
survived. Detections that already carry a non-default explanation are
left untouched.
"""

from __future__ import annotations

from apii.normalize import normalize_arabic
from apii.types import ContextBoostExplanation, DefaultExplanation, Detection, EntityKind

_CONTEXT_WINDOW = 5  # word tokens before a detection that are inspected
_CONTEXT_BOOST = 0.35
_MIN_BOOSTED = 0.4

# Per-kind context words (plain form; normalize_arabic is applied to both
# these and the scanned words before comparison). Context cues, not entity
# value lists — no names/orgs here.
_CONTEXT_TERMS: dict[EntityKind, tuple[str, ...]] = {
    EntityKind.IBAN: ("iban", "آيبان", "ايبان", "الايبان", "حساب", "تحويل", "transfer", "swift"),
    EntityKind.PHONE: ("phone", "mobile", "tel", "call", "جوال", "هاتف", "اتصل", "تواصل", "الجوال", "الهاتف"),
    EntityKind.EMAIL: ("email", "mail", "بريد", "ايميل", "البريد"),
    EntityKind.NATIONAL_ID: ("id", "iqama", "national", "هوية", "الهوية", "اقامة", "الاقامة", "مدني"),
    EntityKind.COMMERCIAL_REGISTRATION: ("cr", "registration", "commercial", "سجل", "تجاري", "السجل"),
    EntityKind.TAX_NUMBER: ("vat", "tax", "trn", "ضريبي", "ضريبة", "زكاة", "الضريبي"),
    EntityKind.PERSON: ("mr", "mrs", "dr", "customer", "client", "name", "السيد", "السيدة", "العميل", "اسم", "الموظف", "المالك"),
    EntityKind.ORGANIZATION: ("company", "co", "ltd", "llc", "شركة", "مؤسسة", "بنك", "مصرف"),
}


def _trailing_words(prefix: str, n: int) -> list[str]:
    """Last `n` word tokens of `prefix` (alphanumeric runs; Arabic letters
    are alphanumeric so Arabic words stay whole). Walks in reverse so cost
    is bounded by the window, not the prefix length."""
    if n == 0:
        return []
    words: list[str] = []
    current: list[str] = []
    for ch in reversed(prefix):
        if ch.isalnum():
            current.append(ch)
        elif current:
            words.append("".join(reversed(current)))
            current = []
            if len(words) >= n:
                break
    if current and len(words) < n:
        words.append("".join(reversed(current)))
    words.reverse()
    return words


def _matched_terms(prefix: str, terms: tuple[str, ...]) -> list[str]:
    normalized_terms = [normalize_arabic(t) for t in terms]
    matched: list[str] = []
    for word in _trailing_words(prefix, _CONTEXT_WINDOW):
        nw = normalize_arabic(word)
        if not nw:
            continue
        if nw in normalized_terms and nw not in matched:
            matched.append(nw)
    return matched


def apply_context_boost(text: str, detections: list[Detection]) -> list[Detection]:
    """Return detections with context-boosted confidence where a context
    word precedes the span. Pure: returns a new list (Detection is frozen)."""
    out: list[Detection] = []
    for d in detections:
        if not isinstance(d.explanation, DefaultExplanation):
            out.append(d)
            continue
        terms = _CONTEXT_TERMS.get(d.kind)
        if not terms:
            out.append(d)
            continue
        matched = _matched_terms(text[: d.start], terms)
        if not matched:
            out.append(d)
            continue
        base = d.confidence
        boosted = max(min(base + _CONTEXT_BOOST, 1.0), _MIN_BOOSTED)
        out.append(
            Detection(
                start=d.start, end=d.end, kind=d.kind, text=d.text,
                confidence=boosted, source=d.source,
                explanation=ContextBoostExplanation(
                    base=base, boost=boosted - base, matched_terms=matched
                ),
            )
        )
    return out
