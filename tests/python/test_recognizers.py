import pytest

from apii import default_pipeline
from apii.evaluate import _eval_root, evaluate
from apii.recognizers import (
    ADDRESS,
    COMMERCIAL_REGISTRATION,
    EMAIL,
    NATIONAL_ID,
    PHONE,
    TAX_NUMBER,
)
from apii.types import EntityKind

# The *_corpus_baseline tests below score against the development gold
# corpus (tests/eval/gold), which is dev-only and not shipped in the
# package. Skip them when that corpus isn't present; the real-corpus pins
# (test_real*_corpus.py) and the per-recognizer unit tests above are the
# product's actual guard rails.
synth_required = pytest.mark.skipif(
    not (_eval_root() / "gold").exists(),
    reason="development gold corpus not present",
)


def _regex_pipeline():
    """Regex-only pipeline — hermetic, no NER, for deterministic checks.

    The product default (default_pipeline()) enables NER when models are
    present; these structured-recognizer tests must not depend on model
    availability, so they force NER off.
    """
    return default_pipeline(enable_ner=False)


def test_email_basic_match():
    dets = list(EMAIL.find("write to Fatima@Example.AE please"))
    assert len(dets) == 1
    d = dets[0]
    assert d.kind is EntityKind.EMAIL
    assert d.text == "Fatima@Example.AE"
    assert d.source == "regex.email"
    assert d.confidence == 0.99


@synth_required
def test_email_corpus_baseline():
    # EMAIL score on the gold corpus: TP=89, FN=1 (a bidi-mark-split
    # address missed until the normalization phase runs). FP is bounded
    # at 12 — the extra over the clean cases is an address nested in a
    # DATABASE_URL, which apii does not pull out as a separate kind.
    res = evaluate(_regex_pipeline())
    email = res.by_kind["EMAIL"]
    assert email.tp == 89
    assert email.fn == 1
    assert email.fp <= 12


def test_phone_saudi_mobile_local_form():
    # `0501234567` — Saudi 05X mobile, the most common gold shape.
    dets = list(PHONE.find("Reach us at 0501234567 anytime."))
    assert len(dets) == 1
    d = dets[0]
    assert d.kind is EntityKind.PHONE
    assert d.confidence == 0.93
    assert d.source == "regex.gcc.phone"
    assert d.text == "0501234567"


def test_phone_international_with_country_code():
    # `+966 50 123 4567` — international form with spaces.
    dets = list(PHONE.find("Call +966 50 123 4567 for support."))
    assert len(dets) == 1
    assert dets[0].text == "+966 50 123 4567"


def test_phone_bare_country_code_prefix_from_pdf_extract():
    # `+`/`00` stripped during PDF extraction (`Bill 966540646444 …`).
    # The 12-digit bare-country-code form is accepted.
    dets = list(PHONE.find("Bill 966540646444 Payment FT2502588TRZ"))
    assert len(dets) == 1
    assert dets[0].text == "966540646444"


def test_phone_rejects_dot_separators():
    # IP-address-like or file-version-like dotted runs must not match —
    # the `.` gate catches these even if the digit count is in range.
    assert list(PHONE.find("v 12.34.56.78.901")) == []


def test_phone_rejects_non_gcc_country_code():
    # `+44 …` is UK; not a GCC prefix → rejected.
    assert list(PHONE.find("Call +44 7700 900123 for UK office.")) == []


def test_phone_boundary_rejects_adjacent_digit():
    # The boundary check drops a candidate whose neighbour is a digit —
    # so a phone shape sliced out of the middle of a longer ID doesn't
    # fire. Surround the otherwise-valid 0501234567 with digits on both
    # sides; the recognizer must not emit anything.
    assert list(PHONE.find("90501234567X")) == []


def test_phone_arabic_indic_via_bare_recognizer_misses():
    # The recognizer alone runs on raw text; GCC_PHONE_RE's `0?5`
    # literal is ASCII, so a pure Arabic-Indic Saudi mobile does not
    # match end-to-end at this layer. The Pipeline is where the
    # digit fold happens — see test_phone_arabic_indic_via_pipeline_hits.
    arabic = "اتصل بـ ٠٥٠١٢٣٤٥٦٧ من فضلك"
    assert list(PHONE.find(arabic)) == []


def test_phone_arabic_indic_via_pipeline_hits():
    # Pipeline.detect runs through normalize_arabic_matching_view, so
    # `٠٥٠١٢٣٤٥٦٧` folds to `0501234567` for matching while the
    # detection span maps back to the original Arabic-Indic positions.
    # The Detection.text is the ORIGINAL Arabic-Indic substring — the
    # anonymizer needs source bytes to do a clean replacement.
    arabic = "اتصل بـ ٠٥٠١٢٣٤٥٦٧ من فضلك"
    dets = _regex_pipeline().detect(arabic)
    phones = [d for d in dets if d.kind is EntityKind.PHONE]
    assert len(phones) == 1
    assert phones[0].text == "٠٥٠١٢٣٤٥٦٧"


def test_nid_uae_emirates_id_bare_shape():
    # UAE Emirates IDs are 784-prefixed, 15 digits with optional dashes.
    dets = list(NATIONAL_ID.find("Emirates ID 784-1990-1234567-1 on file"))
    assert len(dets) == 1
    d = dets[0]
    assert d.kind is EntityKind.NATIONAL_ID
    assert d.confidence == 0.98
    assert d.source == "regex.gcc.uae_id"


def test_nid_saudi_arabic_label_cued():
    # Arabic label "الهوية الوطنية" cues a 10-digit Saudi NID.
    dets = list(NATIONAL_ID.find("الهوية الوطنية: 1010101010"))
    assert len(dets) == 1
    assert dets[0].source == "regex.gcc.saudi_id_context"
    assert dets[0].text == "1010101010"
    assert dets[0].confidence == 0.95


def test_nid_shareholder_dash_bracketed():
    # KYC table extract: name — id — share%
    dets = list(NATIONAL_ID.find("Ahmed Test — 1234567890 — 25%"))
    assert len(dets) == 1
    assert dets[0].source == "regex.shareholder_id"
    assert dets[0].text == "1234567890"
    assert dets[0].confidence == 0.78


@synth_required
def test_nid_corpus_baseline():
    # Baseline (tests/eval/baseline.json): TP=70, FP=0, FN=0 on 70 gold
    # spans — pin all three.
    res = evaluate(_regex_pipeline())
    nid = res.by_kind["NATIONAL_ID"]
    assert nid.tp == 70
    assert nid.fp == 0
    assert nid.fn == 0


def test_cr_arabic_label_cued():
    # السجل التجاري + 10-digit value.
    dets = list(COMMERCIAL_REGISTRATION.find("السجل التجاري: 1010101010"))
    assert len(dets) == 1
    assert dets[0].kind is EntityKind.COMMERCIAL_REGISTRATION
    assert dets[0].source == "regex.gcc.commercial_registration_context"
    assert dets[0].confidence == 0.93


def test_cr_pure_letter_value_rejected():
    # CR captures need at least one digit (there is no usable CR
    # checksum, so the digit-presence gate is the last line of defense
    # against pure-letter captures).
    assert list(COMMERCIAL_REGISTRATION.find("CR Test")) == []


def test_cr_consumes_number_word_and_cr_parenthetical():
    # Real registries write "Commercial Registration Number: <digits>"
    # and "Commercial Registration (CR) Number: <digits>" — the label
    # words must be consumed so the 10-digit value is captured (real
    # corpus: SABIC 1010010813, Jarir 1010032264).
    a = list(COMMERCIAL_REGISTRATION.find("Commercial Registration Number: 1010010813"))
    assert any(d.text == "1010010813" for d in a), a
    b = list(COMMERCIAL_REGISTRATION.find("Commercial Registration (CR) Number: 1010032264"))
    assert any(d.text == "1010032264" for d in b), b


def test_cr_rejects_15_digit_vat_shape():
    # A 15-digit pure-numeric value is the GCC VAT format, never a Saudi
    # CR (10 digits) — so "VAT registration number: <15 digits>" must NOT
    # be tagged CR (it belongs to TAX_NUMBER). Guards the real-corpus bug
    # where CR's generic "registration number" cue stole VAT numbers.
    dets = list(COMMERCIAL_REGISTRATION.find("VAT registration number: 300000316410003"))
    assert dets == []


def test_phone_parenthesized_country_and_area_codes():
    # Real GCC contact pages: "(+974) 44033333" and "+966 (011) 225 8000".
    assert any(
        d.text == "(+974) 44033333" for d in PHONE.find("Call (+974) 44033333 now")
    )
    assert any(
        "(011)" in d.text for d in PHONE.find("Tel: +966 (011) 225 8000 ext")
    )


@synth_required
def test_cr_corpus_baseline():
    # Baseline: TP=27, FP=5, FN=3 — the `regex` library's stricter
    # Unicode \b drops boundary-fragile FPs. Pin TP/FN; bound FP at ≤5
    # (anything higher is a real regression).
    res = evaluate(_regex_pipeline())
    cr = res.by_kind["COMMERCIAL_REGISTRATION"]
    assert cr.tp == 27
    assert cr.fn == 3
    assert cr.fp <= 5


def test_tax_saudi_bare_3_bookended():
    # Saudi VAT shape: 15 digits bookended by 3.
    dets = list(TAX_NUMBER.find("VAT 300000000000003 ok"))
    by_source = {d.source for d in dets}
    assert "regex.saudi_vat_bare" in by_source
    # The label-cued pass also fires on the same span; resolve_overlaps
    # in the pipeline will pick one. The recognizer itself emits both.


def test_tax_bare_15_requires_document_context():
    # Bare 15-digit without any tax-doc trigger → no detection.
    assert list(TAX_NUMBER.find("ref 100000000000001 ok")) == []
    # Same digit run inside a "tax invoice" → emitted via bare-15 pass.
    dets = list(TAX_NUMBER.find("Tax invoice ref 100000000000001 ok"))
    assert any(d.source == "regex.tax_context_bare_15" for d in dets)


def test_tax_bare_15_all_same_char_placeholder_rejected():
    # The all_same_char guard sits on the BARE-15 pass — a 15-digit
    # placeholder inside a tax-doc context does not get a free pass
    # through the bare-15 recognizer. The label-cued pass has no such
    # guard (the label is the precision signal) and still emits.
    dets = list(TAX_NUMBER.find("Tax invoice ref 111111111111111 ok"))
    sources = {d.source for d in dets}
    assert "regex.tax_context_bare_15" not in sources


@synth_required
def test_tax_corpus_baseline():
    # Baseline: TP=22, FP=0, FN=0 (precision 1.0, recall 1.0).
    res = evaluate(_regex_pipeline())
    tax = res.by_kind["TAX_NUMBER"]
    assert tax.tp == 22
    assert tax.fn == 0
    assert tax.fp <= 1


def test_address_po_box_label_cued():
    dets = list(ADDRESS.find("P.O. Box: 12345 Riyadh"))
    sources = {d.source for d in dets}
    assert "regex.address_po_box" in sources


def test_address_arabic_compound_chains_keywords():
    # Compound Saudi address: multiple structural keywords + city.
    text = "حي العليا، شارع الملك فهد، الرياض"
    dets = list(ADDRESS.find(text))
    assert any(d.source == "regex.address_compound" for d in dets)


def test_address_stoplist_drops_tax_registration_swallow():
    # Tail content like "tax registration" indicates the address-context
    # capture is swallowing form/doc boilerplate, not a real address.
    text = "Address: 123 Tax registration office"
    dets = [d for d in ADDRESS.find(text) if d.source == "regex.address_context"]
    assert dets == []


@synth_required
def test_address_corpus_baseline():
    # Baseline (tests/eval/baseline.json): TP=54, FP=0, FN=0 (precision
    # 1.0, recall 1.0) on 45 gold spans — the `regex` library's stricter
    # Unicode \b plus the conservative stoplist drop boundary FPs. FP
    # bound is set with headroom; TP/FN are pinned.
    res = evaluate(_regex_pipeline())
    addr = res.by_kind["ADDRESS"]
    assert addr.tp == 54
    assert addr.fn == 0
    assert addr.fp <= 10


# PERSON and ORGANIZATION are NER-only — there are no regex recognizers
# for them. Their detection is exercised in tests/python/test_ner.py
# (engine unit tests) and tests/python/test_ner_pipeline.py (the merged
# pipeline). No regex PERSON/ORG tests live here by design.


@synth_required
def test_phone_corpus_baseline():
    # Full plausibility + boundary gates on the gold corpus: TP=99, FP=0,
    # FN=0. The "00"+country-code international prefix (00966555550808 …)
    # is accepted by plausible_gcc_phone, so all 99 gold phones are
    # caught. Pinned; never weaken.
    res = evaluate(_regex_pipeline())
    phone = res.by_kind["PHONE"]
    assert phone.tp == 99
    assert phone.fn == 0
    assert phone.fp <= 1
