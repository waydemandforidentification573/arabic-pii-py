"""PDF adapter — extract per-page text + redact_document round-trip.

External deps are skip-guarded so the base suite stays green without
them: pypdf does the extraction (the adapter's hard requirement) and
reportlab builds the in-memory sample PDF the test feeds in.
"""

from __future__ import annotations

import io

import pytest

pytest.importorskip("pypdf")
reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")
from reportlab.lib.pagesizes import letter  # noqa: E402

from apii import default_pipeline  # noqa: E402
from apii.anonymizer import Anonymizer  # noqa: E402
from apii.documents import DocumentKind, extract_for_kind, redact_document  # noqa: E402
from apii.documents._base import DocumentError, PdfPage  # noqa: E402
from apii.documents.pdf import PdfAdapter  # noqa: E402

PHONE = "0501234567"
EMAIL = "a@b.ae"


def _make_pdf(page_lines: list[str]) -> bytes:
    """Render one drawString per page into an in-memory PDF."""
    buf = io.BytesIO()
    c = reportlab_canvas.Canvas(buf, pagesize=letter)
    for line in page_lines:
        c.drawString(72, 720, line)
        c.showPage()
    c.save()
    return buf.getvalue()


def test_extract_text_and_per_page_segments():
    data = _make_pdf([f"Customer phone {PHONE}", f"Email {EMAIL} please"])
    assert data[:5] == b"%PDF-"

    ex = extract_for_kind(DocumentKind.PDF, data)

    assert ex.kind is DocumentKind.PDF
    # Both PII values made it into the extracted text intact.
    assert PHONE in ex.text
    assert EMAIL in ex.text

    # One segment per page, 1-based PdfPage, in order.
    assert len(ex.segments) == 2
    assert ex.segments[0].source == PdfPage(page=1)
    assert ex.segments[1].source == PdfPage(page=2)

    # Each segment's char range slices its own page text out of ex.text,
    # and the ranges don't overlap (separator sits between them).
    s0, s1 = ex.segments
    assert PHONE in ex.text[s0.text_range[0]:s0.text_range[1]]
    assert EMAIL in ex.text[s1.text_range[0]:s1.text_range[1]]
    assert s0.text_range[1] <= s1.text_range[0]
    # Offsets are end-exclusive char indices into ex.text.
    assert s1.text_range[1] <= len(ex.text)


def test_single_page_extract():
    data = _make_pdf([f"Reach {EMAIL} or {PHONE}"])
    ex = extract_for_kind(DocumentKind.PDF, data)
    assert len(ex.segments) == 1
    assert ex.segments[0].source == PdfPage(page=1)
    assert ex.segments[0].text_range[0] == 0


def test_corrupt_pdf_raises_document_error():
    with pytest.raises(DocumentError):
        PdfAdapter.extract(b"%PDF-1.7\nthis is not a real pdf body")


def test_emit_flattens_to_anonymized_txt():
    # PDF output flattens to txt: emit returns the anonymized text bytes.
    assert DocumentKind.PDF.output_extension() == "txt"
    assert not DocumentKind.PDF.preserves_layout()
    out = PdfAdapter.emit(b"", None, "hello PHONE_DEADBEEF")  # type: ignore[arg-type]
    assert out == b"hello PHONE_DEADBEEF"


def test_redact_document_round_trip_restores_original():
    data = _make_pdf([f"Customer phone {PHONE}", f"Email {EMAIL} please"])
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))

    # What the detector sees (so we can assert the exact restored string).
    extracted = extract_for_kind(DocumentKind.PDF, data)
    original_text = extracted.text

    kind, out, report = redact_document(data, a, kind=DocumentKind.PDF)
    assert kind is DocumentKind.PDF

    redacted = out.decode("utf-8")
    # PII is gone, tokens are in.
    assert PHONE not in redacted
    assert EMAIL not in redacted
    assert "PHONE_" in redacted
    assert "EMAIL_" in redacted

    # Round-trip: the same anonymizer's vault restores the extracted text
    # verbatim — page separators and all.
    assert a.deanonymize(redacted) == original_text
