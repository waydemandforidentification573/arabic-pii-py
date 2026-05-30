"""Reversible tokenization round-trip + token-scheme tests.

Uses a regex-only pipeline (enable_ner=False) so these are hermetic and
fast — they exercise the anonymizer mechanics, not NER.
"""

from __future__ import annotations

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.types import EntityKind


def _anon(secret="s3cr3t", tenant="acme", session=None):
    return Anonymizer(secret, tenant, session=session, pipeline=default_pipeline(enable_ner=False))


def test_token_shape_and_prefix():
    a = _anon()
    tok = a.token_for_value(EntityKind.EMAIL, "Ahmed@Example.AE")
    assert tok.startswith("EMAIL_")
    suffix = tok.split("_", 1)[1]
    assert len(suffix) == 16
    assert all(c in "0123456789ABCDEF" for c in suffix)


def test_token_is_deterministic_per_normalized_value():
    a = _anon()
    # Two surface forms of the same email normalize identically → same token.
    t1 = a.token_for_value(EntityKind.EMAIL, "Ahmed@Example.AE")
    t2 = a.token_for_value(EntityKind.EMAIL, "ahmed@example.ae")
    assert t1 == t2


def test_token_differs_by_secret_and_tenant():
    base = _anon(secret="k1", tenant="acme").token_for_value(EntityKind.PHONE, "0501234567")
    other_secret = _anon(secret="k2", tenant="acme").token_for_value(EntityKind.PHONE, "0501234567")
    other_tenant = _anon(secret="k1", tenant="globex").token_for_value(EntityKind.PHONE, "0501234567")
    assert base != other_secret
    assert base != other_tenant


def test_session_scoping_changes_token_but_stays_stable_within_session():
    no_sess = _anon().token_for_value(EntityKind.PHONE, "0501234567")
    s1a = _anon(session="conv-1").token_for_value(EntityKind.PHONE, "0501234567")
    s1b = _anon(session="conv-1").token_for_value(EntityKind.PHONE, "0501234567")
    s2 = _anon(session="conv-2").token_for_value(EntityKind.PHONE, "0501234567")
    assert s1a == s1b  # stable within a session
    assert s1a != s2  # different across sessions
    assert s1a != no_sess  # session-scoped differs from session-unaware


def test_anonymize_replaces_detected_spans_with_tokens():
    a = _anon()
    text = "Email ahmed@example.ae or call 0501234567 today"
    rep = a.anonymize(text)
    assert "ahmed@example.ae" not in rep.text
    assert "0501234567" not in rep.text
    assert "EMAIL_" in rep.text
    assert "PHONE_" in rep.text
    # Records cover both entities.
    kinds = {r.kind for r in rep.records}
    assert EntityKind.EMAIL in kinds and EntityKind.PHONE in kinds


def test_round_trip_restores_original_values():
    a = _anon()
    text = "Reach ahmed@example.ae, IBAN SA0380000000608010167519, phone 0501234567."
    rep = a.anonymize(text)
    restored = a.deanonymize(rep.text)
    assert restored == text


def test_repeated_value_collapses_to_one_token():
    a = _anon()
    text = "call 0501234567 then 0501234567 again"
    rep = a.anonymize(text)
    phone_tokens = {tok for tok in rep.text.split() if tok.startswith("PHONE_")}
    assert len(phone_tokens) == 1  # same value → same token both times


def test_deanonymize_across_instances_via_records():
    a = _anon()
    text = "IBAN SA0380000000608010167519 and email ahmed@example.ae"
    rep = a.anonymize(text)
    # A fresh anonymizer loaded only from the exported records restores it.
    b = Anonymizer.from_records(
        "s3cr3t", "acme", rep.records, pipeline=default_pipeline(enable_ner=False)
    )
    assert b.deanonymize(rep.text) == text


def test_unrestored_token_reported():
    a = _anon()
    # A token-shaped string with no vault entry stays put + is reported.
    report = a.deanonymize_with_report("see EMAIL_DEADBEEF1234 please")
    assert report.text == "see EMAIL_DEADBEEF1234 please"
    assert "EMAIL_DEADBEEF1234" in report.unrestored_tokens


def test_token_values_are_stable():
    # Pinned canonical token values for a fixed secret/tenant. These guard
    # the token scheme (field order, 0x1F separators, HMAC-SHA256,
    # digest[:8] upper-hex) so the derivation stays byte-stable across
    # releases — regenerate only on an intentional algorithm change.
    a = _anon(secret="test-secret", tenant="tenant-a")
    assert a.token_for_value(EntityKind.EMAIL, "ahmed@example.ae") == "EMAIL_18686338BC2AD87A"
    assert a.token_for_value(EntityKind.PHONE, "0501234567") == "PHONE_D9E4E10C9DD1E02E"


def test_anonymize_is_idempotent_on_already_tokenized_text():
    a = _anon()
    text = "phone 0501234567"
    once = a.anonymize(text).text
    twice = a.anonymize(once).text
    # The token itself isn't PII, so a second pass leaves it unchanged.
    assert once == twice
