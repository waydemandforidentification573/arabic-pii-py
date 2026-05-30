"""Recall pins against the REAL corpus (tests/eval/real).

The real corpus is 102 spans sourced from public pages (verified by
tests/eval/real/verify_gold.py: byte-offset round-trip + MOD-97). These
pins guard RECALL — the trustworthy metric here. Precision is deliberately
NOT pinned tight: the gold labels only specific verified spans per
document, so NER correctly finding additional real entities (سابك, Saudi
Exchange, Tadawul, …) that the gold didn't label reads as "false
positives" it shouldn't be penalized for.

The regex layer is hermetic (no models). The NER-enabled pins skip when
the [ner] extra / models are absent.
"""

from __future__ import annotations

import pytest

from apii import default_pipeline
from apii.evaluate import _real_root, evaluate
from apii.ner import ner_available, shared_engines

_REAL = _real_root()
_HAVE_REAL = (_REAL / "gold").exists()
_HAVE_NER = ner_available() and len(shared_engines()) > 0

real_required = pytest.mark.skipif(not _HAVE_REAL, reason="real corpus not present")
ner_required = pytest.mark.skipif(
    not (_HAVE_REAL and _HAVE_NER), reason="real corpus + NER models required"
)


@real_required
def test_regex_layer_recall_on_real_corpus():
    res = evaluate(default_pipeline(enable_ner=False), root=_REAL)
    bk = res.by_kind
    # Structured kinds the regex layer must nail on real public data.
    assert bk["EMAIL"].recall == 1.0
    assert bk["IBAN"].recall == 1.0  # MOD-97 on real IBANs
    assert bk["TAX_NUMBER"].recall == 1.0
    assert bk["COMMERCIAL_REGISTRATION"].recall == 1.0
    assert bk["PHONE"].recall >= 0.9  # bare 8-digit locals deliberately unmatched
    # IBAN precision IS trustworthy (MOD-97 gate) — keep it high.
    assert bk["IBAN"].precision >= 0.85


@ner_required
def test_ner_layer_recall_on_real_corpus():
    res = evaluate(default_pipeline(enable_ner=True), root=_REAL)
    bk = res.by_kind
    # NER is the sole authority for PERSON/ORG and adds ADDRESS (LOC).
    assert bk["PERSON"].recall >= 0.8
    assert bk["ORGANIZATION"].recall >= 0.9
    assert bk["ADDRESS"].recall >= 0.9
    # Overall recall across all in-scope kinds.
    assert res.overall.recall >= 0.85
    # Long documents must not crash NER (the >512-token windowing).
    # If they did, ORG recall would collapse — already asserted above.
