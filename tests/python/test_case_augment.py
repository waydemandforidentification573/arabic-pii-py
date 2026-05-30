"""Case-augmentation: lowercase-name recovery for the cased English NER.

A *cased* model (dslim/bert-base-NER) leans on capitalization, so a
fully-lowercase "talk to michael brown" slips through while "Michael Brown"
is caught. apii.ner runs a length-preserving title-cased second pass and
merges its PERSON spans back. These tests cover the two halves:

  • the casing/gating helpers (no model needed — pure functions), and
  • the engine behaviour on real names (skips without the [ner] extra).

Real common names only — never invented placeholders (the model scores
those unpredictably; that would test the input, not the engine).
"""

from __future__ import annotations

import pytest

from apii.ner import (
    _should_augment,
    _title_variant,
    ner_available,
    shared_english,
)
from apii.types import EntityKind

_EN = shared_english() if ner_available() else None
english_required = pytest.mark.skipif(
    _EN is None, reason="English NER model unavailable (need apii[ner] + models/en-ner)"
)


# ── pure helpers (no model) ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "src",
    [
        "hello and talk to michael brown",
        "email khalid al-otaibi at the office",
        "تحدث إلى خالد — call 0501234567",  # mixed Arabic/ASCII/digits
        "MiXeD cAsE w/ punctuation!! 123",
        "",
    ],
)
def test_title_variant_is_length_preserving(src):
    """Offsets only stay valid if recasing never changes string length."""
    out = _title_variant(src)
    assert len(out) == len(src)
    # every position differs only by ASCII a-z → A-Z, nothing else moves
    for a, b in zip(src, out):
        assert a == b or (a.lower() == b.lower() and a.isascii())


def test_title_variant_capitalizes_word_initials_only():
    assert _title_variant("talk to michael brown") == "Talk To Michael Brown"
    # non-ASCII (Arabic) untouched; interior letters preserved
    assert _title_variant("خالد jane-AL") == "خالد Jane-AL"


def test_should_augment_gating():
    # auto (default): only fully-lowercase input
    assert _should_augment("talk to michael brown", "auto") is True
    assert _should_augment("Talk to michael", "auto") is False   # a capital → skip
    assert _should_augment("CONTACT MICHAEL", "auto") is False    # no lowercase
    assert _should_augment("١٢٣ ٤٥٦", "auto") is False            # no ASCII letters
    # always fires regardless of case (but still needs lowercase to recover)
    assert _should_augment("Talk to michael", "always") is True
    assert _should_augment("CONTACT", "always") is False
    # off never fires
    assert _should_augment("talk to michael", "off") is False


# ── engine behaviour (needs the model) ──────────────────────────────────────

def _persons(text):
    return {text[d.start:d.end] for d in _EN.detect(text) if d.kind is EntityKind.PERSON}


@english_required
def test_lowercase_person_is_recovered():
    # a fully-lowercase name must be caught, not left in plaintext
    assert "michael brown" in _persons("hello 0577941039 and talk to michael brown")
    assert "laura" in _persons("talk to laura about the lead")


@english_required
def test_lowercase_and_cased_yield_the_same_span_text():
    # the recovered span carries the ORIGINAL (lowercase) surface, so the
    # downstream HMAC sees a value consistent with the cased detection.
    low = {t.lower() for t in _persons("talk to michael brown")}
    cased = {t.lower() for t in _persons("Talk to Michael Brown")}
    assert "michael brown" in low and "michael brown" in cased


@english_required
def test_lowercase_compound_name_is_covered_as_one_span():
    # a hyphenated lowercase name must be covered whole, with no plaintext
    # name fragment left behind in the output.
    text = "email khalid al-otaibi at the office"
    persons = [d for d in _EN.detect(text) if d.kind is EntityKind.PERSON]
    assert persons, "expected a PERSON span"
    covered = "".join(text[d.start:d.end] for d in persons)
    assert "khalid" in covered  # the head is inside a token, not leaked


@english_required
def test_cased_prose_is_unaffected_by_augmentation():
    # augmentation must not fire on normal cased text → identical detections
    text = "Contact Michael Brown about the Acme deal."
    base = sorted((d.start, d.end, d.kind) for d in _EN.detect(text))
    import os

    os.environ["APII_NER_CASE_AUG"] = "off"
    try:
        off = sorted((d.start, d.end, d.kind) for d in _EN.detect(text))
    finally:
        del os.environ["APII_NER_CASE_AUG"]
    assert base == off


@english_required
def test_off_knob_disables_lowercase_recovery():
    import os

    os.environ["APII_NER_CASE_AUG"] = "off"
    try:
        assert _persons("talk to michael brown") == set()  # back to cased-only
    finally:
        del os.environ["APII_NER_CASE_AUG"]
