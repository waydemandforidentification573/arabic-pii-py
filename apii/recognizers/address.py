"""ADDRESS recognizer — sub-passes covering Arabic + English forms.

Each sub-pass emits an ADDRESS Detection independently; resolve_overlaps
in Pipeline merges adjacent ones. The variety reflects the reality of
Saudi/GCC address blocks: bank statements emit each field as a short
labeled run (BLDG / PO BOX / postal code / district / street), so
matching has to be both label-cued AND structural. The label-cued
passes gate captured values via `_valid_address_value` to drop captures
swallowing tail content like "البريدي" or "the following".
"""

from __future__ import annotations

from typing import Iterator

import regex

from apii.normalize import normalize_arabic
from apii.recognizers._context import context_capture, regex_matches
from apii.types import Detection, EntityKind

ADDRESS_CONTEXT_RE = regex.compile(
    r"(?:العنوان|عنوان العميل|address(?:\s+at)?|registered\s+address(?:\s+at)?)"
    r"\s*[:#\-]?\s*(?P<v>[\p{Arabic}A-Za-z0-9٠-٩۰-۹\s,\-/]{8,80})",
    regex.UNICODE,
)

# Address sub-field recognizers. Each fires independently; overlap
# resolution merges where they touch.
BLDG_RE = regex.compile(
    r"\b(?:BLDG|BUILDING|UNIT|PLOT|رقم\s+(?:المبنى|قطعة|الوحدة))\b"
    r"\s*\.?\s*(?:no\.?|number|\#)?\s*[:\-]?"
    r"\s*(?P<v>[A-Z0-9٠-٩][A-Z0-9٠-٩\-]{0,12})\b",
    regex.IGNORECASE,
)

PO_BOX_RE = regex.compile(
    r"\b(?:P\.?\s*O\.?\s*BOX|POST\s+BOX|ص\.?\s*ب\.?)"
    r"\s*[:#\-]?\s*(?P<v>\d{1,7})\b",
    regex.IGNORECASE,
)

POSTAL_CODE_RE = regex.compile(
    r"\b(?:ZIP(?:\s+CODE)?|POSTAL\s+CODE|الرمز\s+البريدي)"
    r"\s*[:#\-]?\s*(?P<v>\d{4,6})\b",
    regex.IGNORECASE,
)

# Plain regex passes (no `(?P<v>...)` — full match is the entity).
DISTRICT_RE = regex.compile(
    r"(?:\b[A-Z][A-Za-z']{2,}\s+(?:District|Dist\.?|Neighborhood)\b)"
    r"|(?:\b(?:District|Dist\.?|Neighborhood)\s+[A-Z][A-Za-z']{2,}\b)"
)

STREET_RE = regex.compile(
    r"\b(?:Street|St\.?|Rd\.?|Road|Blvd\.?|Boulevard|Avenue|Ave\.?)\b"
    r"\s*[:#\-]?\s*(?P<v>[A-Z][A-Za-z' \-]{2,40})",
    regex.IGNORECASE,
)

ARABIC_ADDR_RE = regex.compile(
    r"\b(?:شارع|حي|طريق|مدينة|قرية|منطقة)\s+[\p{Arabic}A-Za-z0-9]{2,30}"
)

# Compound Saudi addresses: multiple structural keywords chained with
# commas, optionally ending with a known city + postal code.
ARABIC_COMPOUND_ADDR_RE = regex.compile(
    r"(?:حي|شارع|طريق|مدينة|قرية|منطقة|ص\.?\s*ب|صندوق\s+بريد)"
    r"(?:\s+[\p{Arabic}A-Za-z0-9٠-٩]{2,30}){1,3}"
    r"(?:[\s,،]*(?:[\n]|\s{2,}|[,،])\s*(?:"
    r"(?:حي|شارع|طريق|مدينة|قرية|منطقة|ص\.?\s*ب|صندوق\s+بريد)"
    r"(?:\s+[\p{Arabic}A-Za-z0-9٠-٩]{2,30}){1,3}"
    r"|الرياض|جدة|مكة|المدينة|الدمام|الخبر|الظهران|الهفوف|تبوك|أبها|ينبع|بريدة|نجران|حائل|جازان|الطائف|خميس\s+مشيط"
    r"|Riyadh|Jeddah|Makkah|Mecca|Madinah|Medina|Dammam|Khobar|Dhahran|Hofuf|Tabuk|Abha|Yanbu|Buraydah|Najran|Hail|Jazan|Taif"
    r")){1,5}"
    r"(?:\s+[0-9٠-٩]{4,5}(?:[\-\s][0-9٠-٩]{4})?)?",
    regex.UNICODE,
)

# City-anchored: <Arabic/Latin text>, <City> [<postal code>]
ADDRESS_CITY_ANCHOR_RE = regex.compile(
    r"[\p{Arabic}A-Za-z][\p{Arabic}A-Za-z0-9\s\.\-/]{3,80}[,،]\s*"
    r"(?:Riyadh|Jeddah|Makkah|Mecca|Madinah|Medina|Dammam|Khobar|Dhahran|Hofuf|Tabuk|Abha|Yanbu|Buraydah|Buraidah|Qassim|Najran|Hail|Jazan|Taif|Khamis Mushait|Ha'il"
    r"|الرياض|جدة|مكة|المدينة|الدمام|الخبر|الظهران|الهفوف|تبوك|أبها|ينبع|بريدة|نجران|حائل|جازان|الطائف|خميس مشيط)"
    r"(?:\s+\d{4,5})?\b",
    regex.IGNORECASE | regex.UNICODE,
)

# English / transliterated street shapes.
ENGLISH_STREET_RE = regex.compile(
    r"\b(?:[A-Z][A-Za-z'\-]{1,30})(?:\s+[A-Z][A-Za-z'\-]{1,30}){0,4}"
    r"\s+(?:Road|Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Highway|Hwy\.?|Lane|Way|District|Quarter|Neighborhood|Neighbourhood)\b",
    regex.IGNORECASE,
)

# City + postal-code adjacency (`Riyadh 11416`, `21499 Jeddah`).
CITY_POSTAL_RE = regex.compile(
    r"(?:"
    r"(?:Riyadh|Jeddah|Makkah|Mecca|Madinah|Medina|Dammam|Khobar|Dhahran|Hofuf|Tabuk|Abha|Yanbu|Buraydah|Buraidah|Najran|Hail|Jazan|Taif|Khamis\s+Mushait|Ha'il"
    r"|الرياض|جدة|مكة|المدينة|الدمام|الخبر|الظهران|الهفوف|تبوك|أبها|ينبع|بريدة|نجران|حائل|جازان|الطائف|خميس\s+مشيط"
    r")\s*[,،\-]?\s*[0-9٠-٩]{5}(?:[\-\s][0-9٠-٩]{4})?"
    r"|[0-9٠-٩]{5}(?:[\-\s][0-9٠-٩]{4})?\s*[,،\-]?\s*"
    r"(?:Riyadh|Jeddah|Makkah|Mecca|Madinah|Medina|Dammam|Khobar|Dhahran|Hofuf|Tabuk|Abha|Yanbu|Buraydah|Buraidah|Najran|Hail|Jazan|Taif|Khamis\s+Mushait|Ha'il"
    r"|الرياض|جدة|مكة|المدينة|الدمام|الخبر|الظهران|الهفوف|تبوك|أبها|ينبع|بريدة|نجران|حائل|جازان|الطائف|خميس\s+مشيط"
    r")"
    r")\b",
    regex.IGNORECASE | regex.UNICODE,
)

# Stoplist catching captures that swallow tail content the address
# recognizer is not the right owner of (form labels, tax-doc boilerplate).
_ADDRESS_STOP_NORM = (
    "بالضغط",
    "المختصر",
    "التفصيلي",
    "الوطني ومعلومات",
    "البريدي",
)
_ADDRESS_STOP_LOWER = (
    "the following",
    "tax registration",
    "stated in",
    "excuse of",
    "of the branch",
    "for e-com",
    "industry",
)


def _valid_address_value(value: str) -> bool:
    normalized = normalize_arabic(value)
    if any(term in normalized for term in _ADDRESS_STOP_NORM):
        return False
    lower = value.lower()
    return not any(term in lower for term in _ADDRESS_STOP_LOWER)


class AddressRecognizer:
    """Composite recognizer combining context-cued and plain sub-passes."""

    name = "address"
    kind = EntityKind.ADDRESS
    confidence = 0.82  # representative; per-pass overrides on emit
    requires_witness = False

    def find(self, text: str) -> Iterator[Detection]:
        yield from context_capture(
            ADDRESS_CONTEXT_RE, text, EntityKind.ADDRESS, 0.82,
            "regex.address_context", valid=_valid_address_value,
        )
        yield from context_capture(
            BLDG_RE, text, EntityKind.ADDRESS, 0.80,
            "regex.address_building", valid=_valid_address_value,
        )
        yield from context_capture(
            PO_BOX_RE, text, EntityKind.ADDRESS, 0.85,
            "regex.address_po_box", valid=_valid_address_value,
        )
        yield from context_capture(
            POSTAL_CODE_RE, text, EntityKind.ADDRESS, 0.82,
            "regex.address_postal_code", valid=_valid_address_value,
        )
        yield from regex_matches(
            DISTRICT_RE, text, EntityKind.ADDRESS, 0.75,
            "regex.address_district",
        )
        yield from context_capture(
            STREET_RE, text, EntityKind.ADDRESS, 0.78,
            "regex.address_street", valid=_valid_address_value,
        )
        yield from regex_matches(
            ARABIC_ADDR_RE, text, EntityKind.ADDRESS, 0.78,
            "regex.address_arabic_keyword",
        )
        yield from regex_matches(
            ARABIC_COMPOUND_ADDR_RE, text, EntityKind.ADDRESS, 0.92,
            "regex.address_compound",
        )
        yield from regex_matches(
            ADDRESS_CITY_ANCHOR_RE, text, EntityKind.ADDRESS, 0.86,
            "regex.address_city_anchor",
        )
        yield from regex_matches(
            ENGLISH_STREET_RE, text, EntityKind.ADDRESS, 0.86,
            "regex.address_english_street",
        )
        yield from regex_matches(
            CITY_POSTAL_RE, text, EntityKind.ADDRESS, 0.90,
            "regex.address_city_postal",
        )
