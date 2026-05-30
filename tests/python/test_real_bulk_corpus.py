"""Recall regression pins against the BULK real corpus (tests/eval/real_bulk).

This is the broad sibling of test_real_corpus.py. Where that file pins the
*curated* 102-span set tight (EMAIL/IBAN/TAX/CR recall == 1.0, on documents
that present each value with its proper label/witness), this file pins the
**1238-span** mechanically-built set, whose distribution is deliberately
harder and more varied: un-cued IDs, Arabic org mentions, bare 8-digit
locals, validator test-vectors in code contexts. Every value is real +
public (verified by tests/eval/real/verify_gold.py: byte round-trip +
MOD-97); none is fabricated.

The floors here are HONEST regression guards — set just below the recall the
engine actually achieves today, NOT aspirational. They are intentionally
LOWER than the curated pins for the label-cued kinds, because real public
pages frequently mention a CR or national-ID number with no detector
witness, and those un-cued mentions are not claimed (label-cued detection by
design). Precision is NOT pinned (except IBAN, whose MOD-97 gate makes it
trustworthy): the gold labels one verified value per context, so NER
correctly surfacing the *other* real entities in the same sentence reads as
"false positives" it must not be penalized for.

Measured today (locked as floors below):
  regex  EMAIL 1.00  IBAN 1.00  ADDRESS 0.98  TAX 0.84
         CR 0.76  PHONE 0.79  NATIONAL_ID 0.32
  +NER   PERSON 0.91  ORGANIZATION 0.80  ADDRESS 1.00  overall ~0.89

See tests/eval/real_bulk/README.md for per-kind provenance + ceiling notes.
"""

from __future__ import annotations

import pytest

from apii import default_pipeline
from apii.evaluate import _real_root, evaluate
from apii.ner import ner_available, shared_engines

_BULK = _real_root().parent / "real_bulk"
_HAVE_BULK = (_BULK / "gold").exists()
_HAVE_NER = ner_available() and len(shared_engines()) > 0

bulk_required = pytest.mark.skipif(not _HAVE_BULK, reason="bulk real corpus not present")
ner_required = pytest.mark.skipif(
    not (_HAVE_BULK and _HAVE_NER), reason="bulk real corpus + NER models required"
)


@bulk_required
def test_regex_layer_recall_on_bulk_corpus():
    res = evaluate(default_pipeline(enable_ner=False), root=_BULK)
    bk = res.by_kind
    # Hermetic, deterministic kinds — pinned tight (margin guards one odd value).
    assert bk["EMAIL"].recall >= 0.99
    assert bk["IBAN"].recall >= 0.99      # MOD-97 on 145 real IBANs
    assert bk["IBAN"].precision >= 0.90   # the one trustworthy precision (checksum-gated)
    assert bk["ADDRESS"].recall >= 0.93   # regex geo layer
    assert bk["TAX_NUMBER"].recall >= 0.80
    # Label-cued kinds — honestly lower on un-cued real prose. This is the
    # intended witness-gated design on a hard set.
    assert bk["COMMERCIAL_REGISTRATION"].recall >= 0.72
    assert bk["PHONE"].recall >= 0.74     # bare 8-digit locals unmatched by design
    # Documented ceiling: real individual IDs aren't public, so these are
    # published validator test-vectors, usually un-cued.
    assert bk["NATIONAL_ID"].recall >= 0.28


@ner_required
def test_ner_layer_recall_on_bulk_corpus():
    res = evaluate(default_pipeline(enable_ner=True), root=_BULK)
    bk = res.by_kind
    # NER is the SOLE authority for PERSON/ORG and adds ADDRESS (LOC). These
    # are the headline numbers for the NER-only-names/orgs mandate at scale.
    assert bk["PERSON"].recall >= 0.85
    assert bk["ORGANIZATION"].recall >= 0.74
    assert bk["ADDRESS"].recall >= 0.95
    # Overall recall across all in-scope kinds on the broad real set.
    assert res.overall.recall >= 0.85
    # Long Arabic/English docs must not crash NER (the >512-token windowing):
    # if windowing failed, ORG/PERSON recall above would collapse.
