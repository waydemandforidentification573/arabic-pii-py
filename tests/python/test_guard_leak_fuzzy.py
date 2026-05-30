"""Egress leak gate, residual guard, and fuzzy token restore."""

from __future__ import annotations

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.guard import ResidualGuard
from apii.leak_gate import has_residual_pii


def _anon():
    return Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))


# ── leak_gate ──

def test_leak_gate_detects_raw_pii():
    assert has_residual_pii("contact ahmed@example.com")
    assert has_residual_pii("IBAN SA0380000000608010167519")
    assert has_residual_pii("+966 50 123 4567")
    assert has_residual_pii("0501234567")


def test_leak_gate_ignores_our_tokens():
    assert not has_residual_pii("contact EMAIL_A1B2C3D4E5 please")
    assert not has_residual_pii("via BANK_ALRAJHI on CHANNEL_POS")


def test_leak_gate_clean_prose_passes():
    assert not has_residual_pii("هذه فقرة نظيفة بدون أي معرفات.")


def test_leak_gate_catches_real_leak_beside_token():
    assert has_residual_pii("from EMAIL_A1B2C3D4E5 to leak@example.com")


# ── guard ──

def test_strict_guard_fails_on_residual_pii():
    a = _anon()
    report = ResidualGuard.strict().check_text(a, "call 0501234567")
    assert not report.passed
    assert report.detections


def test_strict_guard_passes_clean_text():
    a = _anon()
    report = ResidualGuard.strict().check_text(a, "PHONE_A1B2C3D4E5 only")
    assert report.passed
    assert not report.detections


def test_ensure_text_raises_on_residual():
    a = _anon()
    try:
        ResidualGuard.strict().ensure_text(a, "call 0501234567")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on residual PII")


# ── fuzzy token restore ──

def test_fuzzy_restore_recovers_mangled_token():
    a = _anon()
    rep = a.anonymize("phone 0501234567")
    token = [t for t in rep.text.split() if t.startswith("PHONE_")][0]
    # The model flips the last hex char of the token.
    last = token[-1]
    flipped = "0" if last != "0" else "1"
    mangled = token[:-1] + flipped
    restored = a.deanonymize(f"the number is {mangled}")
    assert "0501234567" in restored  # recovered despite the flipped digit


def test_fuzzy_restore_leaves_unrelated_token_shapes_alone():
    a = _anon()
    a.anonymize("phone 0501234567")  # vault has one PHONE token
    # A totally unrelated token shape (distance > 2 from any vault token)
    # is reported unrestored, not wrongly substituted.
    report = a.deanonymize_with_report("see EMAIL_DEADBEEF99 here")
    assert "EMAIL_DEADBEEF99" in report.unrestored_tokens
