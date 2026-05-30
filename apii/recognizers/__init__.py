"""Concrete recognizers and the default detection set."""

from __future__ import annotations

import regex

from apii.recognizers.address import AddressRecognizer
from apii.recognizers.commercial_registration import CommercialRegistrationRecognizer
from apii.recognizers.iban import IbanRecognizer
from apii.recognizers.national_id import NationalIdRecognizer
from apii.recognizers.pattern import PatternRecognizer
from apii.recognizers.phone import PhoneRecognizer
from apii.recognizers.tax_number import TaxNumberRecognizer
from apii.types import EntityKind

EMAIL = PatternRecognizer(
    name="email",
    kind=EntityKind.EMAIL,
    pattern=regex.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", regex.IGNORECASE),
    confidence=0.99,
    source="regex.email",
)

# Placed right after EMAIL so its span claims an IBAN before NER can
# mislabel it as ORG in the merge.
IBAN = IbanRecognizer()

PHONE = PhoneRecognizer()

NATIONAL_ID = NationalIdRecognizer()

COMMERCIAL_REGISTRATION = CommercialRegistrationRecognizer()

TAX_NUMBER = TaxNumberRecognizer()

# Bank account numbers and passport numbers are intentionally not detected:
# an account number has no self-identifying structure (no checksum or fixed
# length), so context-free it can't be told apart from any other digit run,
# and IBAN already covers structured money-routing; passport numbers are
# alphanumeric and collide with SKUs / order codes, making context-free
# matching too false-positive-prone to be useful.

ADDRESS = AddressRecognizer()

# PERSON and ORGANIZATION have NO regex recognizer — by design. Name and
# organization detection is handled SOLELY by the NER engines
# (apii.ner: hatmimoha/arabic-ner + dslim/bert-base-NER), merged into the
# pipeline via apii.ner_merge. Regex name/org matching is too brittle
# across Arabic + transliterated + Latin forms to be worth the precision
# cost; the models carry it.

# The structured recognizers the default pipeline runs, in detection
# order. Order is load-bearing: resolve_overlaps breaks ties on
# first-emitted, so reordering silently drifts source attribution even
# when TP counts match. PERSON / ORGANIZATION are absent here on purpose
# (NER-only); NER also contributes ADDRESS (model LOC) on top of these.
DEFAULT_RECOGNIZERS = (
    EMAIL,
    IBAN,
    PHONE,
    NATIONAL_ID,
    COMMERCIAL_REGISTRATION,
    TAX_NUMBER,
    ADDRESS,
)

__all__ = [
    "PatternRecognizer",
    "IbanRecognizer",
    "PhoneRecognizer",
    "NationalIdRecognizer",
    "CommercialRegistrationRecognizer",
    "TaxNumberRecognizer",
    "AddressRecognizer",
    "EMAIL",
    "IBAN",
    "PHONE",
    "NATIONAL_ID",
    "COMMERCIAL_REGISTRATION",
    "TAX_NUMBER",
    "ADDRESS",
    "DEFAULT_RECOGNIZERS",
]
