"""Text normalization + offset map.

Two views on the same text. Recognizers run on the *normalized* view
(NFKC + Arabic letter unification + diacritic strip + digit fold), but
their detections must land at the original character positions. The
[`NormalizedText`] offset map closes that loop: a recognizer reports
`(normalized_start, normalized_end)`; `original_span` translates it back.

All offsets here are Python str character indices (not UTF-8 bytes).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import msgspec

# Arabic-Indic (U+0660-0669) and Persian/Extended-Arabic (U+06F0-06F9)
# digits folded to ASCII — only these two non-ASCII digit families are
# recognized, nothing else.
_DIGIT_FOLD = {0x0660 + i: chr(0x30 + i) for i in range(10)} | {
    0x06F0 + i: chr(0x30 + i) for i in range(10)
}


def ascii_digit(ch: str) -> str | None:
    """Return the ASCII digit equivalent of `ch`, or None if not a digit.

    Accepts ASCII, Arabic-Indic, and Persian/Extended-Arabic digit families.
    """
    if len(ch) != 1:
        return None
    if "0" <= ch <= "9":
        return ch
    folded = _DIGIT_FOLD.get(ord(ch))
    return folded


def normalize_digits(value: str) -> str:
    """Fold Arabic-Indic and Persian digits to ASCII; leave other chars."""
    return value.translate(_DIGIT_FOLD)


def digits_only(value: str) -> str:
    """Keep only digits, Arabic/Persian folded to ASCII."""
    return "".join(c for c in normalize_digits(value) if c.isascii() and c.isdigit())


def alnum_upper(value: str) -> str:
    """Fold digits, keep only ASCII alphanumerics, uppercase."""
    return "".join(c for c in normalize_digits(value) if c.isascii() and c.isalnum()).upper()


# Arabic-letter codepoint ranges.
_ARABIC_RANGES = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
)


def is_arabic_letter(ch: str) -> bool:
    """True iff `ch` is a single Arabic-script codepoint."""
    if len(ch) != 1:
        return False
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _ARABIC_RANGES)


def is_arabic_word(value: str) -> bool:
    """True iff every non-trivial char in `value` is Arabic.

    Spaces, dashes, ZWJ/ZWNJ, and Arabic diacritics count as
    "trivial" passthrough; any non-Arabic letter rejects.
    """
    has_arabic = False
    for ch in value:
        cp = ord(ch)
        if (
            0x0600 <= cp <= 0x06FF
            or 0x0750 <= cp <= 0x077F
            or 0x08A0 <= cp <= 0x08FF
        ):
            has_arabic = True
        elif ch in (" ", "-") or cp in (0x200C, 0x200D) or 0x064B <= cp <= 0x065F or cp == 0x0670:
            continue
        else:
            return False
    return has_arabic


# Invisible / formatting codepoints stripped before detection (scrubber).
# Excludes Arabic ZWNJ (200C) / ZWJ (200D) — those are legitimate
# orthography in Persian and Arabic words.
def _is_strippable_invisible(cp: int) -> bool:
    return (
        cp == 0x200B  # zero-width space
        or cp == 0x200E  # LRM
        or cp == 0x200F  # RLM
        or 0x202A <= cp <= 0x202E  # bidi embeddings + overrides
        or 0x2060 <= cp <= 0x2064  # word joiner + invisible math
        or 0x2066 <= cp <= 0x2069  # bidi isolates
        or cp == 0xFEFF  # BOM
        or cp == 0x00AD  # soft hyphen
        or cp == 0x180E  # Mongolian vowel separator
        or 0xE0000 <= cp <= 0xE007F  # Unicode Tag block (tag smuggling)
    )


# Visually-identical Cyrillic confusables → Latin.
_HOMOGLYPH = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "ѕ": "s", "і": "i", "ј": "j",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
}


def scrub_invisible(text: str) -> str:
    """Strip zero-width / bidi / tag chars and fold Cyrillic homoglyphs.

    Idempotent. Closes a zero-width / look-alike evasion class. Arabic
    ZWNJ/ZWJ are preserved (they're real orthography).
    """
    out: list[str] = []
    for ch in text:
        if _is_strippable_invisible(ord(ch)):
            continue
        out.append(_HOMOGLYPH.get(ch, ch))
    return "".join(out)


def reverse_arabic_runs(text: str) -> str:
    """Character-reverse each maximal run of Arabic letters in place.

    Used to recover logical order from PDF extractors that emit RTL in
    visual order. Non-Arabic characters and run boundaries are
    unchanged, so per-run CHAR ranges remain valid against the original —
    detection spans on the reversed view can be reused 1:1.
    """
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            out.extend(reversed(run))
            run.clear()

    for ch in text:
        if is_arabic_letter(ch):
            run.append(ch)
        else:
            flush()
            out.append(ch)
    flush()
    return "".join(out)


def strip_arabic_prefix_particles(word: str) -> str:
    """Strip Arabic clitic prefixes (ال, بال, و, ب, …) if ≥3 chars remain."""
    for prefix in ("بال", "وال", "فال", "كال", "لل", "ال", "ب", "و"):
        if word.startswith(prefix):
            rest = word[len(prefix):]
            if len(rest) >= 3:
                return rest
    return word


# ── Full Arabic normalization (used by context / lexicon comparisons) ──

# Letter unification.
_LETTER_FOLD = {
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي",
    "ة": "ه",
    "ؤ": "و",
    "ئ": "ي",
}


def _strip_arabic_diacritics(text: str) -> str:
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if 0x064B <= cp <= 0x065F or cp == 0x0670 or 0x06D6 <= cp <= 0x06ED:
            continue
        if ch == "ـ":  # tatweel
            continue
        out.append(ch)
    return "".join(out)


def normalize_arabic(value: str) -> str:
    """Full Arabic letter unification + lowercase + whitespace collapse.

    Loses positional information — intended for *comparing* strings
    (context-word match, lexicon lookup), not for replacing text in
    place. Use `normalize_arabic_matching_view` when offsets matter.
    """
    nfkc = unicodedata.normalize("NFKC", value)
    stripped = _strip_arabic_diacritics(nfkc)
    folded = "".join(_LETTER_FOLD.get(ch, ch) for ch in stripped)
    digit_folded = normalize_digits(folded)
    return " ".join(digit_folded.split()).lower()


# ── Matching view with offset map (the hard one) ──


class _NormalizedSpan(msgspec.Struct, frozen=True):
    normalized_start: int
    normalized_end: int
    original_start: int
    original_end: int


@dataclass(frozen=True)
class NormalizedText:
    """A normalized view of source text + a char-offset map back.

    `text` is the normalized string (NFKC, diacritics dropped, digits
    folded). `original_span(ns, ne)` returns the **inclusive bounds**
    of the original-text range that contributed to `text[ns:ne]` — i.e.
    the smallest `(o_s, o_e)` such that every normalized char in
    [ns, ne) came from an original char in [o_s, o_e).

    Recognizers run on `.text` and report normalized spans; the
    pipeline translates each span back via `original_span` before
    emitting Detections in the caller's coordinate space.
    """

    text: str
    _spans: tuple[_NormalizedSpan, ...]

    def original_span(self, normalized_start: int, normalized_end: int) -> tuple[int, int] | None:
        if normalized_start >= normalized_end or normalized_end > len(self.text):
            return None
        first = next(
            (s for s in self._spans if s.normalized_end > normalized_start), None
        )
        if first is None:
            return None
        last = next(
            (s for s in reversed(self._spans) if s.normalized_start < normalized_end),
            None,
        )
        if last is None:
            return None
        return (first.original_start, last.original_end)


def normalize_arabic_matching_view(value: str) -> NormalizedText:
    """NFKC + diacritic drop + digit fold, with a char-offset map back.

    NFKC can split or join codepoints, so 1 source char may emit 0, 1, or
    N normalized chars; each emitted char gets a span whose original range
    is the source char's char-position window.
    """
    out: list[str] = []
    spans: list[_NormalizedSpan] = []
    for original_start, ch in enumerate(value):
        original_end = original_start + 1
        for nch in unicodedata.normalize("NFKC", ch):
            cp = ord(nch)
            # Arabic diacritics + tatweel collapse to nothing.
            if (
                0x064B <= cp <= 0x065F
                or cp == 0x0670
                or 0x06D6 <= cp <= 0x06ED
                or nch == "ـ"
            ):
                continue
            mapped = ascii_digit(nch) or nch
            normalized_start = len(out)
            out.append(mapped)
            spans.append(
                _NormalizedSpan(
                    normalized_start=normalized_start,
                    normalized_end=normalized_start + 1,
                    original_start=original_start,
                    original_end=original_end,
                )
            )
    return NormalizedText(text="".join(out), _spans=tuple(spans))


def normalize_for_kind(kind, value: str) -> str:
    """Canonical form of a value for its kind. The token vault keys on
    this so that two surface forms of the same entity (``SA03 8000…`` vs
    ``sa0380 00…``, ``Ahmed@X.AE`` vs ``ahmed@x.ae``) collapse to one
    stable token.

    Imported lazily-typed (kind is apii.types.EntityKind) to avoid a
    circular import at module load.
    """
    from apii.types import EntityKind

    if kind is EntityKind.EMAIL:
        return value.strip().lower()
    if kind in (
        EntityKind.PHONE,
        EntityKind.COMMERCIAL_REGISTRATION,
        EntityKind.TAX_NUMBER,
        EntityKind.NATIONAL_ID,
    ):
        return digits_only(value)
    if kind == EntityKind.IBAN:
        return alnum_upper(value)
    if kind in (EntityKind.PERSON, EntityKind.ORGANIZATION, EntityKind.ADDRESS):
        return normalize_arabic(value)
    return value.strip()


def normalize(text: str) -> str:
    """Pipeline-level normalizer hook — a pass-through.

    The Pipeline calls this before fanning out to recognizers. The real
    normalization work lives in the helpers above (scrub_invisible,
    normalize_arabic_matching_view, …), which the recognizers apply where
    it matters; this hook must stay length-stable (preserve character
    offsets), so it returns the text unchanged.
    """
    return text
