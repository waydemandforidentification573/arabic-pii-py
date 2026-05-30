"""PII entity kinds, detection explanations, and the Detection struct."""

from __future__ import annotations

import enum
from typing import Union

import msgspec


class EntityKind(enum.Enum):
    """PII categories apii detects.

    Each value is the SCREAMING_SNAKE_CASE wire name used throughout the
    library, so detections compare by plain string equality.

    By design, apii focuses on Arabic/GCC personal data and leaves a few
    classes to specialized tooling:
      - API keys / JWTs / PEM keys — use a secret scanner (gitleaks,
        trufflehog), which is purpose-built for credential shapes.
      - Payment cards — regulated under PCI-DSS; route card data through a
        PCI tokenizer rather than a general-purpose redactor.
      - Arbitrary company-issued codes (CIF, ticket refs, invoice IDs,
        payroll codes) have no standardized format or checksum, so reliable
        detection needs a per-tenant pattern list; supply one in your own
        pre-processing pass if you need it.
    """

    EMAIL = "EMAIL"
    PHONE = "PHONE"
    IBAN = "IBAN"
    COMMERCIAL_REGISTRATION = "COMMERCIAL_REGISTRATION"
    TAX_NUMBER = "TAX_NUMBER"
    NATIONAL_ID = "NATIONAL_ID"
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    ADDRESS = "ADDRESS"

    @property
    def token_prefix(self) -> str:
        """Stable prefix used in placeholder tokens (e.g. ORG, GOV_ID)."""
        return _TOKEN_PREFIX[self]


_TOKEN_PREFIX: dict[EntityKind, str] = {
    EntityKind.EMAIL: "EMAIL",
    EntityKind.PHONE: "PHONE",
    EntityKind.IBAN: "IBAN",
    EntityKind.COMMERCIAL_REGISTRATION: "CR",
    EntityKind.TAX_NUMBER: "TAX_ID",
    EntityKind.NATIONAL_ID: "GOV_ID",
    EntityKind.PERSON: "PERSON",
    EntityKind.ORGANIZATION: "ORG",
    EntityKind.ADDRESS: "ADDRESS",
}


class DefaultExplanation(msgspec.Struct, frozen=True, tag="default", tag_field="explanation"):
    """No structured rationale beyond the recognizer's source name."""


class FixedMappingExplanation(
    msgspec.Struct, frozen=True, tag="fixed_mapping", tag_field="explanation"
):
    """Matched a canonical dictionary entry (bank, telco, government body)."""

    entity: str


class ValidatorExplanation(
    msgspec.Struct, frozen=True, tag="validator", tag_field="explanation"
):
    """Confirmed (or rejected) by a checksum / format validator."""

    name: str
    passed: bool


class ContextBoostExplanation(
    msgspec.Struct, frozen=True, tag="context_boost", tag_field="explanation"
):
    """Score raised because context words appeared near the span."""

    base: float
    boost: float
    matched_terms: list[str]


# Tagged union; the JSON representation carries `"explanation": "default"`
# (etc.) as the tag field.
DetectionExplanation = Union[
    DefaultExplanation,
    FixedMappingExplanation,
    ValidatorExplanation,
    ContextBoostExplanation,
]

DEFAULT_EXPLANATION = DefaultExplanation()


class Detection(msgspec.Struct, frozen=True):
    """One detected PII span.

    `start`/`end` are character offsets (never byte positions) into the
    normalized text the pipeline ran on.
    """

    start: int
    end: int
    kind: EntityKind
    text: str
    confidence: float
    source: str
    explanation: DetectionExplanation = DEFAULT_EXPLANATION
