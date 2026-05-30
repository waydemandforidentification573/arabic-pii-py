"""Structured (JSON) key-hint anonymization."""

from __future__ import annotations

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.structured import (
    anonymize_structured,
    deanonymize_structured,
    looks_like_placeholder,
    sensitive_key_kind,
)
from apii.types import EntityKind


def _anon():
    return Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))


def test_sensitive_key_kind_maps_keys():
    assert sensitive_key_kind("cr_number", "1010123456") is EntityKind.COMMERCIAL_REGISTRATION
    assert sensitive_key_kind("customer_name", "Sarah Johnson") is EntityKind.PERSON
    assert sensitive_key_kind("iban", "SA0380000000608010167519") is EntityKind.IBAN
    # amount/date fields are explicitly skipped
    assert sensitive_key_kind("balance", "5591674.08") is None
    assert sensitive_key_kind("transaction_date", "2026-01-01") is None
    assert sensitive_key_kind(None, "x") is None


def test_key_contains_exact_segment_for_simple_words():
    # `max_tokens` must NOT match the `token`-class terms (not a detected
    # kind anyway here, but the segment rule is what prevents the false
    # hit): a "vat" field matches, "private" does not match "vat".
    assert sensitive_key_kind("vat_number", "300000000000003") is EntityKind.TAX_NUMBER
    assert sensitive_key_kind("private_field", "x") is None


def test_unsupported_keys_yield_no_kind():
    # secret/card/internal-code keys map to no kind apii detects — they
    # fall through to text detection instead.
    assert sensitive_key_kind("api_key", "abcdef") is None
    assert sensitive_key_kind("card_number", "4111111111111111") is None
    assert sensitive_key_kind("cif", "557788") is None


def test_person_key_requires_alphabetic_value():
    assert sensitive_key_kind("customer_name", "Ahmed") is EntityKind.PERSON
    assert sensitive_key_kind("customer_name", "12345") is None  # no letters → not a name


def test_looks_like_placeholder():
    assert looks_like_placeholder("CR_A1B2C3D4E5")
    assert looks_like_placeholder("BANK_ALRAJHI")
    assert not looks_like_placeholder("1010123456")
    assert not looks_like_placeholder("hello_world")


def test_anonymize_structured_tokenizes_by_key_and_round_trips():
    a = _anon()
    doc = {
        "customer_name": "Sarah Johnson",
        "cr_number": "1010123456",        # bare id — only the KEY reveals it
        "contact": {"email": "a@b.ae", "phone": "0501234567"},
        "balance": "5591674.08",          # amount — must NOT be touched
        "shareholders": ["1010111111", "1010222222"],  # CR list via parent key...
        "notes": "call me at 0501234567",  # free text → text detection
    }
    out = anonymize_structured(doc, a)
    assert out["customer_name"].startswith("PERSON_")
    assert out["cr_number"].startswith("CR_")
    assert out["contact"]["email"].startswith("EMAIL_")
    assert out["contact"]["phone"].startswith("PHONE_")
    assert out["balance"] == "5591674.08"  # untouched
    assert "0501234567" not in out["notes"]  # free-text phone redacted
    # numbers/shape preserved; restore round-trips
    restored = deanonymize_structured(out, a)
    assert restored["customer_name"] == "Sarah Johnson"
    assert restored["cr_number"] == "1010123456"
    assert restored["contact"]["email"] == "a@b.ae"
    assert restored["notes"] == "call me at 0501234567"


def test_already_tokenized_value_is_left_alone():
    a = _anon()
    doc = {"customer_name": "PERSON_DEADBEEF1234"}
    out = anonymize_structured(doc, a)
    assert out["customer_name"] == "PERSON_DEADBEEF1234"
