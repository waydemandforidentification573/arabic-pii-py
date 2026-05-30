"""NER engine unit tests — real names.

These exercise apii.ner against the int8 ONNX models (models/arabic-ner,
models/en-ner). They skip cleanly when the [ner] extra or the model files
are absent, so the base test suite stays green in a CI without
onnxruntime/models.

Correctness rests on REAL public-figure names and place names the
underlying models were trained to recognize — invented placeholder names
("…الاختباري") are deliberately avoided, since the models score them
unpredictably and that would test the input, not the engine.
"""

from __future__ import annotations

import pytest

from apii.ner import ner_available, shared_arabic, shared_english
from apii.types import EntityKind

_AR = shared_arabic() if ner_available() else None
_EN = shared_english() if ner_available() else None

arabic_required = pytest.mark.skipif(
    _AR is None, reason="Arabic NER model unavailable (need apii[ner] + models/arabic-ner)"
)
english_required = pytest.mark.skipif(
    _EN is None, reason="English NER model unavailable (need apii[ner] + models/en-ner)"
)
# The corrupt-override test copies the real bundled model files as its base;
# skip it when those aren't checked out locally (e.g. the standalone package,
# where the 210 MB models are hosted externally, not in the tree).
import os as _os  # noqa: E402

bundled_model_files = pytest.mark.skipif(
    not _os.path.exists("models/arabic-ner/config.json"),
    reason="bundled model files absent (standalone package; models hosted externally)",
)


def _kinds(dets):
    return {(d.kind, d.text) for d in dets}


@arabic_required
def test_arabic_person_and_location():
    # Real public figure + capital city. The Arabic model (hatmimoha/
    # arabic-ner) tags محمد بن سلمان as PERSON and الرياض as LOCATION→Address.
    dets = _AR.detect("اجتمع محمد بن سلمان مع وزير الخارجية في الرياض")
    persons = [d for d in dets if d.kind is EntityKind.PERSON]
    addresses = [d for d in dets if d.kind is EntityKind.ADDRESS]
    assert any("محمد بن سلمان" in d.text for d in persons), persons
    assert any("الرياض" in d.text for d in addresses), addresses
    # Every emission carries the NER source + a real probability.
    for d in dets:
        assert d.source == "ner.onnx"
        assert 0.85 <= d.confidence <= 1.0


@arabic_required
def test_arabic_organization():
    # Real Saudi company. Arabic ORG NER fires standalone (no witness gate
    # for Arabic-script spans).
    dets = _AR.detect("تأسست شركة أرامكو السعودية في الظهران")
    orgs = [d for d in dets if d.kind is EntityKind.ORGANIZATION]
    assert orgs, dets


@english_required
def test_english_person_multitoken_wordpiece():
    # "Khalid Al-Otaibi" splits into Khalid / Al / - / O / ##tai / ##bi.
    # The WordPiece merge + BIO aggregation must recover the WHOLE span,
    # not a fragment like "bi".
    dets = _EN.detect("Mr. Khalid Al-Otaibi joined the board.")
    persons = [d for d in dets if d.kind is EntityKind.PERSON]
    assert persons, dets
    # The merged span covers the full name (head offset preserved).
    assert any("Khalid" in d.text and "Otaibi" in d.text for d in persons), persons


@english_required
def test_english_org_wordpiece_merge():
    # "Aljazira Bank" → Al / ##ja / ##zi / ##ra / Bank. Merge must yield
    # one ORG span, not five fragments.
    dets = _EN.detect("transferred funds to Aljazira Bank yesterday")
    orgs = [d for d in dets if d.kind is EntityKind.ORGANIZATION]
    assert any("Bank" in d.text for d in orgs), orgs


@english_required
def test_english_location_maps_to_address():
    # CoNLL LOC → Address (matching emit_span's LOC→Address mapping).
    dets = _EN.detect("The meeting was held in Riyadh last week.")
    assert any(d.kind is EntityKind.ADDRESS for d in dets), dets


@arabic_required
def test_blank_input_returns_empty():
    assert _AR.detect("   ") == []


@arabic_required
def test_offsets_are_char_based_and_slice_correctly():
    # The Python tokenizers lib returns CHAR offsets; Detection.text must
    # equal text[start:end] exactly (no byte/char drift).
    text = "اجتمع محمد بن سلمان في جدة"
    dets = _AR.detect(text)
    assert dets
    for d in dets:
        assert d.text == text[d.start : d.end]


@arabic_required
def test_long_document_over_512_tokens_does_not_crash_and_keeps_recall():
    # BERT caps at 512 positions; a longer doc would crash the ONNX graph.
    # The engine windows the input — so a >512-token document still runs
    # AND a name late in the document (past token 512) is still found.
    filler = "هذا نص حشو طويل جدا لاختبار التقطيع الى نوافذ. " * 60  # >512 tokens
    text = filler + " وأخيرا التقى محمد بن سلمان بالوفد في جدة."
    dets = _AR.detect(text)  # must not raise
    persons = [d for d in dets if d.kind is EntityKind.PERSON]
    assert any("محمد بن سلمان" in d.text for d in persons), "name past token 512 must still be found"
    # Offsets from a late window still slice correctly.
    for d in dets:
        assert d.text == text[d.start : d.end]


@english_required
def test_patronymic_bin_does_not_fragment_or_leak_name():
    # The model O-tags "bin" inside transliterated names, which without the
    # bridge fragments the span AND can drop a borderline tail token below
    # 0.85 — leaking a real name in plaintext
    # ("Khalid bin Sultan" → "<token> bin Sultan"). The bridge keeps the
    # PERSON span whole so every name token is covered by one detection.
    for name in ("Khalid bin Sultan", "Mohammed bin Rashid Al Maktoum"):
        dets = _EN.detect(name)
        persons = [d for d in dets if d.kind is EntityKind.PERSON]
        assert persons, (name, dets)
        # One span must cover the whole name — no trailing token left bare.
        covering = [d for d in persons if d.start == 0 and d.end == len(name)]
        assert covering, (name, [(d.start, d.end, d.text) for d in persons])


def test_ner_threshold_env_is_robust():
    # A missing / empty / malformed APII_NER_THRESHOLD must fall back to
    # 0.85, NOT raise — a raise would be swallowed into a None engine,
    # silently disabling NER. Pure-function test, no model needed.
    import os

    from apii.ner import _DEFAULT_THRESHOLD, _threshold_from_env

    saved = os.environ.get("APII_NER_THRESHOLD")
    try:
        for bad in ("", "xyz", "  "):
            os.environ["APII_NER_THRESHOLD"] = bad
            assert _threshold_from_env() == _DEFAULT_THRESHOLD, bad
        os.environ["APII_NER_THRESHOLD"] = "0.6"
        assert _threshold_from_env() == 0.6
        os.environ.pop("APII_NER_THRESHOLD", None)
        assert _threshold_from_env() == _DEFAULT_THRESHOLD
    finally:
        if saved is None:
            os.environ.pop("APII_NER_THRESHOLD", None)
        else:
            os.environ["APII_NER_THRESHOLD"] = saved


@pytest.mark.skipif(not ner_available(), reason="needs apii[ner]")
@bundled_model_files
def test_corrupt_override_model_degrades_to_none_not_crash(tmp_path, monkeypatch):
    # A corrupt model behind APII_NER_MODEL must degrade (return None / fall
    # to bundled), never raise out of the factory.
    import shutil

    from apii.ner import NerEngine
    src = "models/arabic-ner"
    shutil.copy(f"{src}/tokenizer.json", tmp_path / "tokenizer.json")
    shutil.copy(f"{src}/config.json", tmp_path / "config.json")
    (tmp_path / "model_quantized.onnx").write_bytes(b"garbage" * 100)
    monkeypatch.setenv("APII_NER_MODEL", str(tmp_path))
    # Must not raise; override fails → falls through to the bundled model.
    eng = NerEngine.from_env_or_bundled("APII_NER_MODEL", "arabic-ner")
    assert eng is None or isinstance(eng, NerEngine)


def test_ner_available_is_bool():
    # Always runs — documents the import-guard contract.
    assert isinstance(ner_available(), bool)
