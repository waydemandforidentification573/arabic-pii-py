"""NATIONAL_ID recognizer — UAE 784-shape + Saudi/GCC label-cued forms.

Four sub-recognizers, all emitting EntityKind.NATIONAL_ID:

  1. Bare 784-prefixed 15-digit UAE shape with optional separators.
  2. Arabic/English Saudi-NID labels (`الهوية الوطنية`, `iqama`,
     `national id`, …) cueing an 8-15 digit value.
  3. Broader GCC label set (CPR, `قطر id`, `الرقم المدني`, …) cueing
     8-12 digit values.
  4. Bare 9-15 digit run bracketed by dashes or pipes — the column-
     extracted KYC / payroll table shape.

Validation is regex + label only (no Luhn / mod-11): the shared
`apii.checksums.luhn` and `kuwait_mod11` primitives are available, but
checksum-gating national IDs costs more recall than the precision it
buys on real data, so it is left off.
"""

from __future__ import annotations

from typing import Iterator

import regex

from apii.recognizers._context import context_capture
from apii.types import Detection, EntityKind

UAE_ID_RE = regex.compile(
    r"\b784[\- ]?[0-9٠-٩۰-۹]{4}[\- ]?[0-9٠-٩۰-۹]{7}[\- ]?[0-9٠-٩۰-۹]\b"
)

SAUDI_ID_CONTEXT_RE = regex.compile(
    r"(?:رقم\s+)?"
    r"(?:الهوية\s+الوطنية|هوية\s+الوطنية|الهوية|هوية|السجل\s+المدني|الإقامة|الاقامة"
    r"|iqama|national\s*id|civil\s*id|saudi\s*id|nat\s*id"
    r"|qatar\s*id\s*\(?qid\)?|qid|emirates\s*id|gcc\s*id"
    r"|bahrain\s*id|kuwait\s*id|oman\s*id|id\s*(?:no|number|\#))"
    r"\s*\.?\s*[:#\-]?\s*(?P<v>[0-9٠-٩۰-۹]{8,15})",
    regex.IGNORECASE,
)

GCC_ID_CONTEXT_RE = regex.compile(
    r"(?:civil\s*id|qatar\s*id|cpr|رقم\s+مدني|البطاقة\s+المدنية"
    r"|الرقم\s+الشخصي|الرقم\s+المدني|الرقم\s+السکاني|الرقم\s+السكاني)"
    r"\s*[:#\-]?\s*(?P<v>[0-9٠-٩۰-۹]{8,12})",
    regex.IGNORECASE,
)

# Bare 9-12-digit IDs bracketed by en-dashes, em-dashes, or pipes —
# column-extracted shareholder / KYC / payroll table rows.
SHAREHOLDER_ID_RE = regex.compile(
    r"[—–\-|]\s*(?P<v>[0-9٠-٩۰-۹]{9,15})\s*[—–\-|]"
)


class NationalIdRecognizer:
    """Composite recognizer; emits one stream from four sub-patterns."""

    name = "national_id"
    kind = EntityKind.NATIONAL_ID
    confidence = 0.95  # representative; per-pattern overrides on emit
    requires_witness = False

    def find(self, text: str) -> Iterator[Detection]:
        for m in UAE_ID_RE.finditer(text):
            yield Detection(
                start=m.start(),
                end=m.end(),
                kind=EntityKind.NATIONAL_ID,
                text=m.group(),
                confidence=0.98,
                source="regex.gcc.uae_id",
            )
        yield from context_capture(
            SAUDI_ID_CONTEXT_RE,
            text,
            EntityKind.NATIONAL_ID,
            0.95,
            "regex.gcc.saudi_id_context",
        )
        yield from context_capture(
            GCC_ID_CONTEXT_RE,
            text,
            EntityKind.NATIONAL_ID,
            0.90,
            "regex.gcc.id_context",
        )
        yield from context_capture(
            SHAREHOLDER_ID_RE,
            text,
            EntityKind.NATIONAL_ID,
            0.78,
            "regex.shareholder_id",
        )
