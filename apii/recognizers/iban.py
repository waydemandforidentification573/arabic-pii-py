"""GCC IBAN recognizer — MOD-97 only. Checksum is the truth.

Validity is purely ISO 7064 MOD-97 (identical across all six GCC
countries — SA / AE / QA / KW / BH / OM). A detection is emitted ONLY
when the candidate has the correct per-country length AND passes MOD-97;
a corrupted IBAN fails the checksum and is dropped. An earlier
"context_fallback" tier that accepted checksum-FAILING IBANs near the
word "IBAN" was deliberately removed.

Bank-name resolution (mapping the BBAN bank code to an institution) is a
SEPARATE metadata concern, intentionally not part of detection — a valid
IBAN is valid regardless of whether its bank code is in any table.
"""

from __future__ import annotations

from typing import Iterator

import regex

from apii.checksums import iban_mod97
from apii.normalize import alnum_upper
from apii.types import Detection, EntityKind, ValidatorExplanation

# Country code → full IBAN length (country + 2 check digits + BBAN).
_IBAN_LEN = {"SA": 24, "AE": 23, "QA": 29, "KW": 30, "BH": 22, "OM": 23}

# Alphanumerics AFTER the 2-letter country prefix = total length − 2.
# Matching an exact count per country (tolerant of internal whitespace /
# dashes from OCR or grouped display) makes the regex robust against
# greedily over-grabbing a trailing alnum char.
_AFTER = {cc: length - 2 for cc, length in _IBAN_LEN.items()}

# Digit class admits ASCII, Arabic-Indic (U+0660-0669), Persian
# (U+06F0-06F9); the alnum class adds A-Z.
_D = r"0-9٠-٩۰-۹"
_A = r"A-Z" + _D

# country prefix + 2 CHECK DIGITS (digit-class only) + the remaining
# BBAN alnum chars.
_COUNTRY_PARTS = [
    rf"{cc}(?:[\s\-]*[{_D}]){{2}}(?:[\s\-]*[{_A}]){{{n - 2}}}" for cc, n in _AFTER.items()
]
# Each branch: country prefix + exactly N more alnum chars (each
# optionally preceded by whitespace/dash). Word-bounded so it won't slice
# out of the middle of a longer token.
IBAN_RE = regex.compile(
    r"\b(?:" + "|".join(_COUNTRY_PARTS) + r")\b",
    regex.IGNORECASE,
)


def _valid_gcc_iban(normalized: str) -> bool:
    """True iff `normalized` (alnum_upper) is a checksum-valid GCC IBAN."""
    expected = _IBAN_LEN.get(normalized[:2])
    if expected is None or len(normalized) != expected:
        return False
    # ISO 7064 MOD-97 over the rearranged IBAN (country+check moved to end).
    return iban_mod97(normalized[4:] + normalized[:4]) == 1


class IbanRecognizer:
    """Single pass: shape match → fold → length + MOD-97 → emit if valid."""

    name = "iban"
    kind = EntityKind.IBAN
    confidence = 0.99
    requires_witness = False

    def find(self, text: str) -> Iterator[Detection]:
        for m in IBAN_RE.finditer(text):
            raw = m.group()
            normalized = alnum_upper(raw)
            if not _valid_gcc_iban(normalized):
                continue
            yield Detection(
                start=m.start(),
                end=m.end(),
                kind=EntityKind.IBAN,
                text=raw,
                confidence=0.99,
                source="regex.gcc.iban.mod97",
                explanation=ValidatorExplanation(name="iban_mod97", passed=True),
            )
