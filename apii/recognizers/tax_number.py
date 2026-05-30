"""TAX_NUMBER recognizer — three sub-passes for VAT / TRN / Saudi VAT.

  1. Label-cued 10-20 digit value (VAT / TRN / الرقم الضريبي / …).
  2. Bare Saudi VAT shape: 15-digit run bookended by `3` — Saudi VAT
     numbers always start and end with `3`.
  3. Bare 15-digit run, only when the surrounding document context
     contains a tax-document trigger. The `all_same_char` guard rejects
     `111111111111111` / placeholder runs.
"""

from __future__ import annotations

from typing import Iterator

import regex

from apii.normalize import digits_only
from apii.recognizers._context import context_capture
from apii.types import Detection, EntityKind

TAX_NUMBER_RE = regex.compile(
    r"(?:الرقم\s+الضريبي|رقم\s+ضريبي|ضريبة\s+القيمة\s+المضافة"
    r"|القيمة\s+المضافة|VAT|TRN|tax\s*(?:id|number|no)|vat\s*(?:id|number|no)"
    r"|taxpayer(?:\s*(?:id|no|number))?|tax\s+registration)"
    r"\s*[:#\-/]?\s*(?P<v>[0-9٠-٩۰-۹]{10,20})",
    regex.IGNORECASE,
)

SAUDI_VAT_BARE_RE = regex.compile(r"\b[3٣۳][0-9٠-٩۰-۹]{13}[3٣۳]\b")

TAX_CONTEXT_BARE_15_RE = regex.compile(r"\b[0-9٠-٩۰-۹]{15}\b")

# Document-level triggers that license the bare-15 recognizer.
_TAX_DOC_LOWER = (
    "tax invoice",
    "simplified tax invoice",
    "vat",
    "trn",
    "tax registration",
    "e-invoice",
    "e invoice",
    "fatoora",
)
_TAX_DOC_ARABIC = (
    "فاتورة ضريبية",
    "ضريبة القيمة المضافة",
    "القيمة المضافة",
    "الرقم الضريبي",
    "رقم ضريبي",
)


def _has_tax_document_context(text: str) -> bool:
    lower = text.lower()
    return any(t in lower for t in _TAX_DOC_LOWER) or any(t in text for t in _TAX_DOC_ARABIC)


def _all_same_char(value: str) -> bool:
    if not value:
        return False
    first = value[0]
    return all(ch == first for ch in value[1:])


class TaxNumberRecognizer:
    """Three-pass composite: label-cued + Saudi bare + doc-gated bare-15."""

    name = "tax_number"
    kind = EntityKind.TAX_NUMBER
    confidence = 0.93  # representative; per-pass overrides on emit
    requires_witness = False

    def find(self, text: str) -> Iterator[Detection]:
        yield from context_capture(
            TAX_NUMBER_RE,
            text,
            EntityKind.TAX_NUMBER,
            0.93,
            "regex.gcc.tax_number_context",
        )
        for m in SAUDI_VAT_BARE_RE.finditer(text):
            yield Detection(
                start=m.start(),
                end=m.end(),
                kind=EntityKind.TAX_NUMBER,
                text=m.group(),
                confidence=0.86,
                source="regex.saudi_vat_bare",
            )
        # Bare-15 pass runs only inside a tax document.
        if not _has_tax_document_context(text):
            return
        for m in TAX_CONTEXT_BARE_15_RE.finditer(text):
            digits = digits_only(m.group())
            if len(digits) != 15 or _all_same_char(digits):
                continue
            yield Detection(
                start=m.start(),
                end=m.end(),
                kind=EntityKind.TAX_NUMBER,
                text=m.group(),
                confidence=0.80,
                source="regex.tax_context_bare_15",
            )
