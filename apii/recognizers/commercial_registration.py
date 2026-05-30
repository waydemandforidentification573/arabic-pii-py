"""COMMERCIAL_REGISTRATION recognizer — label-cued, structural only.

CR numbers have no usable public checksum: real Saudi CRs sit at the
~10% random-noise floor for every common scheme. The Arabic / English
label set + the digit-presence gate (CR numbers always contain at
least one digit, ASCII or Arabic-Indic) is the precision signal.
"""

from __future__ import annotations

from typing import Iterator

import regex

from apii.recognizers._context import context_capture
from apii.types import Detection, EntityKind

COMMERCIAL_REGISTRATION_RE = regex.compile(
    r"(?:رقم\s+)?"
    r"(?:السجل\s+التجاري|سجل\s+تجاري|فرع\s+السجل\s+التجاري|س\.?\s*ت\.?"
    r"|commercial\s+registration|branch\s*CR|civil\s+register(?:\s*(?:no|number))?"
    r"|company\s+registration(?:\s+number)?|registration\s+(?:no|number)"
    r"|(?:\bCR\b|C\.R\.)(?:\s*(?:no|number|رقم|\#))?)"
    # Optional "(CR)" parenthetical + optional "number/no/رقم" word the
    # label often carries before the value ("Commercial Registration
    # (CR) Number: 1010032264"), so the value capture starts at the digits.
    r"(?:\s*\(\s*CR\s*\))?(?:\s+(?:no\.?|number|رقم))?"
    r"\s*\.?\s*[:#\-/]?\s*(?P<v>[A-Z0-9٠-٩۰-۹][A-Z0-9٠-٩۰-۹\-]{4,18})",
    regex.IGNORECASE,
)

# GCC commercial registrations are short numeric/alnum identifiers (Saudi
# CR = 10 digits; GCC variants like CN-0000777). A pure-15-digit value is
# the GCC VAT registration format, never a CR — rejecting it stops the CR
# recognizer (conf 0.93) from stealing VAT numbers from TAX_NUMBER (which
# the generic "registration number" cue would otherwise grab).
_VAT_DIGIT_LEN = 15


def _digits_only_count(value: str) -> int:
    return sum(1 for ch in value if 0x30 <= ord(ch) <= 0x39 or 0x0660 <= ord(ch) <= 0x0669)


def _looks_like_cr(value: str) -> bool:
    """True iff value has a digit (not pure-letter) AND is not VAT-shaped.

    Keeps pure-letter captures (`CR Test`) out; the VAT-shape guard
    (15 pure digits) rejects tax numbers the generic label cue would grab.
    """
    digits = _digits_only_count(value)
    if digits == 0:
        return False
    # 15 digits and nothing but digits → VAT registration format, not CR.
    if digits == _VAT_DIGIT_LEN and digits == len(value):
        return False
    return True


class CommercialRegistrationRecognizer:
    name = "commercial_registration"
    kind = EntityKind.COMMERCIAL_REGISTRATION
    confidence = 0.93
    requires_witness = False

    def find(self, text: str) -> Iterator[Detection]:
        yield from context_capture(
            COMMERCIAL_REGISTRATION_RE,
            text,
            EntityKind.COMMERCIAL_REGISTRATION,
            0.93,
            "regex.gcc.commercial_registration_context",
            valid=_looks_like_cr,
        )
