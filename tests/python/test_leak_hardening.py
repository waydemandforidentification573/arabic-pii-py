"""Regression tests for leak hardening.

The anonymizer must scrub zero-width / bidi-control / homoglyph chars
before detection, so an invisible char inside a PII value can't make it
survive into the redacted output. The egress gate (has_residual_pii) is
likewise hardened with scrub + Arabic-Indic digit folding.
"""

from __future__ import annotations

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.leak_gate import has_residual_pii


def _anon():
    return Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))


def test_zero_width_split_phone_does_not_leak():
    # ZWSP inside a Saudi mobile — must be scrubbed + redacted, not leaked.
    a = _anon()
    out = a.anonymize("call 050​1234567 now").text
    assert "0501234567" not in out
    assert "05​" not in out  # the zero-width char is gone too
    assert "PHONE_" in out


def test_soft_hyphen_split_iban_does_not_leak():
    a = _anon()
    out = a.anonymize("IBAN SA03­8000­0000­6080­1016­7519").text
    assert "SA0380000000608010167519" not in out
    assert "IBAN_" in out


def test_cyrillic_homoglyph_email_does_not_leak():
    # "ahmed" with a Cyrillic 'а' (U+0430) — folded to ASCII then detected.
    a = _anon()
    out = a.anonymize("mail аhmed@example.com please").text
    assert "@example.com" not in out
    assert "EMAIL_" in out


def test_bidi_control_inside_phone_does_not_leak():
    # An RLM inside the digit run must not defeat detection.
    a = _anon()
    out = a.anonymize("‎0501234567‎").text
    assert "0501234567" not in out
    assert "PHONE_" in out


def test_leak_gate_catches_zero_width_split_value():
    assert has_residual_pii("residual 050​1234567 here")


def test_leak_gate_catches_arabic_indic_phone():
    # Arabic-Indic Saudi mobile folds to ASCII → caught by the gate.
    assert has_residual_pii("٠٥٠١٢٣٤٥٦٧")


def test_leak_gate_still_clean_on_tokenized_text():
    # Hardening must not produce false residual-leak alarms on tokens.
    assert not has_residual_pii("contact EMAIL_A1B2C3D4E5 via PHONE_99AABBCCDD")


def test_clean_text_round_trip_unaffected():
    # Scrubbing is a no-op on clean text → existing round-trip still holds.
    a = _anon()
    text = "Reach ahmed@example.ae or 0501234567."
    rep = a.anonymize(text)
    assert a.deanonymize(rep.text) == text
