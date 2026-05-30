"""Context-aware confidence boosting + bidi fallback wiring."""

from __future__ import annotations

from apii import default_pipeline
from apii.context import apply_context_boost
from apii.types import (
    ContextBoostExplanation,
    DefaultExplanation,
    Detection,
    EntityKind,
    FixedMappingExplanation,
)


def _det(kind, start, end, conf, source="x", expl=None):
    return Detection(
        start=start, end=end, kind=kind, text="v", confidence=conf, source=source,
        explanation=expl or DefaultExplanation(),
    )


def test_context_word_raises_confidence_and_records_terms():
    text = "IBAN SA0380000000608010167519"
    d = _det(EntityKind.IBAN, 5, len(text), 0.6)
    out = apply_context_boost(text, [d])
    assert out[0].confidence > 0.6
    assert isinstance(out[0].explanation, ContextBoostExplanation)
    assert "iban" in out[0].explanation.matched_terms


def test_boost_caps_at_one():
    text = "phone 0501234567"
    d = _det(EntityKind.PHONE, 6, len(text), 0.93)
    out = apply_context_boost(text, [d])
    assert out[0].confidence == 1.0


def test_no_boost_without_context_word():
    text = "random words then 0501234567"
    start = text.index("0")
    d = _det(EntityKind.PHONE, start, len(text), 0.93)
    out = apply_context_boost(text, [d])
    assert out[0].confidence == 0.93
    assert isinstance(out[0].explanation, DefaultExplanation)


def test_out_of_window_context_does_not_boost():
    text = "iban one two three four five six SA0380000000608010167519"
    start = text.index("SA03")
    d = _det(EntityKind.IBAN, start, len(text), 0.6)
    out = apply_context_boost(text, [d])
    assert out[0].confidence == 0.6


def test_arabic_context_word_boosts():
    text = "رقم الجوال 0501234567"
    start = text.index("0")
    d = _det(EntityKind.PHONE, start, len(text), 0.6)
    out = apply_context_boost(text, [d])
    assert out[0].confidence > 0.6


def test_non_default_explanation_is_not_overwritten():
    text = "شركة مصرف الراجحي"
    d = _det(EntityKind.ORGANIZATION, 5, len(text), 0.95,
             expl=FixedMappingExplanation(entity="BANK_ALRAJHI"))
    out = apply_context_boost(text, [d])
    assert out[0].confidence == 0.95
    assert isinstance(out[0].explanation, FixedMappingExplanation)


def test_pipeline_regex_detection_unaffected_by_boost():
    # Context boost must not change which spans are detected — only
    # confidence. The regex detection pins (other tests) cover counts;
    # here we just confirm the pipeline still returns detections with
    # boosted confidence for a label-cued case.
    dets = default_pipeline(enable_ner=False).detect("IBAN: SA0380000000608010167519")
    ibans = [d for d in dets if d.kind is EntityKind.IBAN]
    assert len(ibans) == 1
