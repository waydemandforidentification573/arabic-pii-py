"""IBAN recognizer — MOD-97-only. Checksum is the truth.

Worked-example IBANs are public, checksum-valid vectors (one per GCC
country). Validity rests on ISO 7064 MOD-97, not on any allowlist.
"""

from __future__ import annotations

from apii import default_pipeline
from apii.recognizers import IBAN
from apii.types import EntityKind, ValidatorExplanation

# One public, MOD-97-valid IBAN per GCC country (verified in-test below).
VALID = {
    "SA": "SA0380000000608010167519",
    "AE": "AE070331234567890123456",
    "QA": "QA58DOHB00001234567890ABCDEFG",
    "KW": "KW81CBKU0000000000001234560101",
    "BH": "BH67BMAG00001299123456",
    "OM": "OM810180000001299123456",
}


def test_all_gcc_valid_ibans_detected():
    for cc, iban in VALID.items():
        dets = list(IBAN.find(f"IBAN: {iban} on file"))
        assert len(dets) == 1, (cc, dets)
        d = dets[0]
        assert d.kind is EntityKind.IBAN
        assert d.confidence == 0.99
        assert d.source == "regex.gcc.iban.mod97"
        assert d.text == iban
        assert isinstance(d.explanation, ValidatorExplanation)
        assert d.explanation.name == "iban_mod97"
        assert d.explanation.passed is True


def test_checksum_failing_iban_rejected():
    # Flip one digit of the valid SA IBAN — MOD-97 fails → not emitted.
    bad = "SA0380000000608010167518"  # last digit 9→8
    assert list(IBAN.find(f"IBAN: {bad}")) == []


def test_synthetic_zeroed_iban_rejected():
    # The kind of checksum-invalid placeholder the old gold was full of.
    assert list(IBAN.find("SA0399001111222233334444")) == []
    assert list(IBAN.find("OM81 0180 0000 0000 0000 0000")) == []


def test_grouped_display_with_spaces_validates():
    # Banks print IBANs in 4-char groups; folding strips the spaces.
    grouped = "SA03 8000 0000 6080 1016 7519"
    dets = list(IBAN.find(f"Account {grouped} active"))
    assert len(dets) == 1
    assert dets[0].text == grouped


def test_arabic_indic_digits_fold_for_checksum():
    # Arabic-Indic rendering of the valid SA IBAN validates identically.
    arabic = "SA٠٣٨٠٠٠٠٠٠٠٦٠٨٠١٠١٦٧٥١٩"
    dets = list(IBAN.find(arabic))
    assert len(dets) == 1
    assert dets[0].source == "regex.gcc.iban.mod97"


def test_non_gcc_iban_not_matched():
    # GB (UK) is checksum-valid but not a GCC country → not matched.
    assert list(IBAN.find("GB29NWBK60161331926819")) == []


def test_worked_examples_are_actually_mod97_valid():
    # Guards the test corpus itself: every VALID vector must pass MOD-97.
    from apii.checksums import iban_mod97

    lengths = {"SA": 24, "AE": 23, "QA": 29, "KW": 30, "BH": 22, "OM": 23}
    for cc, iban in VALID.items():
        assert len(iban) == lengths[cc], cc
        assert iban_mod97(iban[4:] + iban[:4]) == 1, cc


def test_pipeline_iban_blocks_ner_org_mislabel():
    # With IBAN back in the pipeline, the IBAN span is claimed by the
    # regex layer, so the NER merge can't mislabel it as ORGANIZATION.
    text = "Transfer to SA0380000000608010167519 today"
    dets = default_pipeline(enable_ner=False).detect(text)
    ibans = [d for d in dets if d.kind is EntityKind.IBAN]
    assert len(ibans) == 1
    assert ibans[0].source == "regex.gcc.iban.mod97"
