"""Integration tests for the NER-enabled pipeline (regex + NER merge).

PERSON and ORGANIZATION are NER-only; these confirm they surface through
the full pipeline, that regex detections coexist, and that the non-overlap
merge lets a structured regex span block an overlapping NER hit.

Skips when the [ner] extra / models are absent so the base suite stays
green in CI.
"""

from __future__ import annotations

import pytest

from apii import default_pipeline
from apii.ner import ner_available, shared_engines
from apii.ner_merge import merge_ner
from apii.types import Detection, EntityKind

_HAVE_NER = ner_available() and len(shared_engines()) > 0

ner_required = pytest.mark.skipif(
    not _HAVE_NER, reason="NER engines unavailable (need apii[ner] + models/)"
)


@ner_required
def test_pipeline_emits_arabic_person_org_address_via_ner():
    p = default_pipeline()  # NER on by default
    text = "اجتمع محمد بن سلمان مع ممثل شركة أرامكو السعودية في الرياض"
    dets = p.detect(text)
    kinds = {d.kind for d in dets}
    assert EntityKind.PERSON in kinds
    assert EntityKind.ORGANIZATION in kinds
    assert EntityKind.ADDRESS in kinds
    # Every NER span carries the engine source.
    ner = [d for d in dets if d.source == "ner.onnx"]
    assert ner
    for d in ner:
        assert d.text == text[d.start : d.end]  # char-offset fidelity


@ner_required
def test_pipeline_regex_and_ner_coexist():
    p = default_pipeline()
    text = "العميل محمد العمري على الجوال 0501234567"
    dets = p.detect(text)
    assert any(d.kind is EntityKind.PHONE and d.source == "regex.gcc.phone" for d in dets)
    assert any(d.kind is EntityKind.PERSON and d.source == "ner.onnx" for d in dets)


@ner_required
def test_ner_disabled_pipeline_has_no_person_or_org():
    p = default_pipeline(enable_ner=False)
    text = "اجتمع محمد بن سلمان مع شركة أرامكو السعودية"
    dets = p.detect(text)
    assert not any(d.kind in (EntityKind.PERSON, EntityKind.ORGANIZATION) for d in dets)


# ── merge_ner unit tests (no models needed) ──


def _det(kind, start, end, source, conf=0.9):
    return Detection(start=start, end=end, kind=kind, text="x", confidence=conf, source=source)


def test_merge_regex_wins_overlap_tie():
    # A regex ADDRESS already occupies [10,20]; an overlapping NER ADDRESS
    # is dropped (regex owns the span).
    resolved = [_det(EntityKind.ADDRESS, 10, 20, "regex.address_city_postal")]
    ner = [_det(EntityKind.ADDRESS, 12, 25, "ner.onnx", 0.99)]
    out = merge_ner(resolved, ner)
    assert len(out) == 1
    assert out[0].source == "regex.address_city_postal"


def test_merge_appends_non_overlapping_ner():
    resolved = [_det(EntityKind.PHONE, 0, 10, "regex.gcc.phone")]
    ner = [_det(EntityKind.PERSON, 20, 33, "ner.onnx")]
    out = merge_ner(resolved, ner)
    assert len(out) == 2
    # Position-sorted.
    assert [d.start for d in out] == [0, 20]


def test_merge_arabic_ner_beats_overlapping_english_ner():
    # NER dets arrive in engine order (Arabic first). The first-added
    # (Arabic) span blocks an overlapping later (English) span.
    arabic = _det(EntityKind.PERSON, 0, 13, "ner.onnx", 0.98)
    english = _det(EntityKind.PERSON, 5, 18, "ner.onnx", 0.99)
    out = merge_ner([], [arabic, english])
    assert len(out) == 1
    assert out[0].end == 13  # the Arabic-first span survived
