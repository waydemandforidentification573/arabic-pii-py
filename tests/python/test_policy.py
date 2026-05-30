"""Policy modes: strict / balanced / audit + redact-kinds."""

from __future__ import annotations

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.policy import AnonymizationMode, AnonymizationPolicy
from apii.types import EntityKind


def _anon(policy):
    return Anonymizer(
        "s", "t", pipeline=default_pipeline(enable_ner=False), policy=policy
    )


def test_mode_parse():
    assert AnonymizationMode.parse("STRICT") is AnonymizationMode.STRICT
    assert AnonymizationMode.parse(" balanced ") is AnonymizationMode.BALANCED
    assert AnonymizationMode.parse("audit") is AnonymizationMode.AUDIT
    try:
        AnonymizationMode.parse("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_strict_redacts_everything_detected():
    rep = _anon(AnonymizationPolicy.strict()).anonymize("email ahmed@example.ae phone 0501234567")
    assert "ahmed@example.ae" not in rep.text
    assert "0501234567" not in rep.text


def test_audit_detects_but_does_not_mutate():
    text = "email ahmed@example.ae phone 0501234567"
    rep = _anon(AnonymizationPolicy.audit()).anonymize(text)
    assert rep.text == text  # unchanged
    assert rep.records == []  # nothing tokenized
    assert len(rep.detections) >= 2  # but still reported


def test_redact_kinds_narrows_to_subset():
    policy = AnonymizationPolicy.strict().with_redact_kinds([EntityKind.PHONE])
    text = "email ahmed@example.ae phone 0501234567"
    rep = _anon(policy).anonymize(text)
    assert "0501234567" not in rep.text  # phone redacted
    assert "ahmed@example.ae" in rep.text  # email left in place
    # Email still reported as a detection.
    assert any(d.kind is EntityKind.EMAIL for d in rep.detections)


def test_empty_redact_kinds_collapses_to_redact_all():
    policy = AnonymizationPolicy.strict().with_redact_kinds([])
    for k in EntityKind:
        assert policy.should_redact(k)


def test_balanced_allowlisted_term_passes_through():
    # An operator marks a public bank name as allowed → it stays verbatim
    # while other PII is still redacted. (No hardcoded institution list —
    # the allowlist is declarative.)
    policy = AnonymizationPolicy.balanced().with_allowed_public_terms(["Al Rajhi Bank"])
    # The org name matches the allowlist key regardless of spacing/case.
    assert policy.replacement_for(EntityKind.ORGANIZATION, "AL RAJHI BANK") == "AL RAJHI BANK"
    assert policy.replacement_for(EntityKind.ORGANIZATION, "مصرف الراجحي") is None  # not in list
    # A non-allowlisted value gets no passthrough (→ caller tokenizes).
    assert policy.replacement_for(EntityKind.ORGANIZATION, "Some Other Co") is None


def test_strict_never_passes_through():
    policy = AnonymizationPolicy.strict().with_allowed_public_terms(["Al Rajhi Bank"])
    assert policy.replacement_for(EntityKind.ORGANIZATION, "Al Rajhi Bank") is None
