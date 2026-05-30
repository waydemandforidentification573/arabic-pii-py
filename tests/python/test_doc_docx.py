"""DOCX adapter — extract granularity + redact_document round-trip.

DOCX is stdlib-only (zipfile + string scanning), so no importorskip
guard is needed here; the base suite stays green regardless.
"""

from __future__ import annotations

import io
import zipfile

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.documents import DocumentKind, extract_for_kind, redact_document
from apii.documents._base import DocxRun
from apii.documents.docx import DocxAdapter

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    "</Relationships>"
)


def _document_xml(runs: list[str]) -> str:
    """Build a word/document.xml where each item in `runs` is one
    <w:t> run, all inside a single paragraph."""
    body = "".join(
        f"<w:r><w:t xml:space=\"preserve\">{r}</w:t></w:r>" for r in runs
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p>{body}</w:p></w:body></w:document>"
    )


def _make_docx(runs: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("word/document.xml", _document_xml(runs))
    return buf.getvalue()


def test_extract_text_and_segments():
    data = _make_docx(["Phone ", "0501234567", " email ", "a@b.ae"])
    ex = extract_for_kind(DocumentKind.DOCX, data)
    assert ex.kind is DocumentKind.DOCX
    SEP = "\x1e"
    # One leaf per non-empty run, joined by the separator.
    assert ex.text == SEP.join(["Phone ", "0501234567", " email ", "a@b.ae"]) + SEP
    assert len(ex.segments) == 4
    # Each segment's char range slices its run body out of ex.text.
    bodies = ["Phone ", "0501234567", " email ", "a@b.ae"]
    for seg, body in zip(ex.segments, bodies):
        s, e = seg.text_range
        assert ex.text[s:e] == body
        assert isinstance(seg.source, DocxRun)
        assert seg.source.paragraph == 0
    # Runs are numbered globally in document order, starting at 0.
    assert [seg.source.run for seg in ex.segments] == [0, 1, 2, 3]


def test_skips_empty_and_lookalike_tags():
    # `<w:tab/>` and a self-closing `<w:t/>` must not become runs; an
    # empty body must be skipped too.
    doc_xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p>"
        "<w:r><w:t>real</w:t></w:r>"
        "<w:r><w:tab/></w:r>"
        "<w:r><w:t></w:t></w:r>"
        "<w:r><w:t/></w:r>"
        "<w:r><w:t>body</w:t></w:r>"
        "</w:p></w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("word/document.xml", doc_xml)
    ex = extract_for_kind(DocumentKind.DOCX, buf.getvalue())
    assert ex.text == "real\x1ebody\x1e"
    assert len(ex.segments) == 2


def test_xml_entities_are_decoded_on_extract():
    data = _make_docx(["A &amp; B &lt;tag&gt;"])
    ex = extract_for_kind(DocumentKind.DOCX, data)
    assert ex.text == "A & B <tag>\x1e"


def test_missing_document_xml_raises():
    import pytest

    from apii.documents._base import DocumentError

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
    with pytest.raises(DocumentError):
        extract_for_kind(DocumentKind.DOCX, buf.getvalue())


def test_bad_zip_raises():
    import pytest

    from apii.documents._base import DocumentError

    with pytest.raises(DocumentError):
        extract_for_kind(DocumentKind.DOCX, b"not a zip at all")


def test_redact_document_round_trip():
    data = _make_docx(["Contact: ", "0501234567", " / ", "a@b.ae", " thanks"])
    original_text = extract_for_kind(DocumentKind.DOCX, data).text

    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    kind, out, report = redact_document(data, a, kind=DocumentKind.DOCX)
    assert kind is DocumentKind.DOCX

    # The emitted file is still a valid docx zip with the PII gone.
    assert out[:4] == b"PK\x03\x04"
    re_extracted = extract_for_kind(DocumentKind.DOCX, out)
    assert "0501234567" not in re_extracted.text
    assert "a@b.ae" not in re_extracted.text
    assert "PHONE_" in re_extracted.text
    assert "EMAIL_" in re_extracted.text

    # Deanonymizing the re-extracted text restores the original extract.
    assert a.deanonymize(re_extracted.text) == original_text


def test_redact_document_partial_run_replacement():
    # The whole point of run-granular DOCX: PII embedded mid-run, with
    # text on both sides, must be replaced in place and round-trip.
    data = _make_docx(["Call 0501234567 today, mail a@b.ae please"])
    original_text = extract_for_kind(DocumentKind.DOCX, data).text

    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    _, out, _ = redact_document(data, a, kind=DocumentKind.DOCX)
    re_extracted = extract_for_kind(DocumentKind.DOCX, out)
    assert "0501234567" not in re_extracted.text
    assert "a@b.ae" not in re_extracted.text
    # Surrounding non-PII text in the same run is preserved.
    assert re_extracted.text.startswith("Call ")
    assert " today, mail " in re_extracted.text
    assert a.deanonymize(re_extracted.text) == original_text


def test_emit_preserves_other_zip_entries():
    data = _make_docx(["Phone ", "0501234567"])
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    _, out, _ = redact_document(data, a, kind=DocumentKind.DOCX)
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(io.BytesIO(out)) as zout:
        in_names = set(zin.namelist())
        out_names = set(zout.namelist())
        assert in_names == out_names
        # Every entry except document.xml is byte-identical.
        for name in in_names:
            if name == "word/document.xml":
                continue
            assert zin.read(name) == zout.read(name)


def test_emit_run_count_mismatch_raises():
    import pytest

    from apii.documents._base import DocumentError

    data = _make_docx(["one", "two"])
    ex = extract_for_kind(DocumentKind.DOCX, data)
    # Hand emit an anonymized string with the wrong number of leaves.
    with pytest.raises(DocumentError):
        DocxAdapter.emit(data, ex, "only-one-leaf")


def test_emit_escapes_special_chars_in_tokens():
    # A leaf containing XML specials must produce valid XML that
    # re-extracts to the same characters.
    data = _make_docx(["plain"])
    ex = extract_for_kind(DocumentKind.DOCX, data)
    out = DocxAdapter.emit(data, ex, "a < b & c > d \x1e")
    re_extracted = extract_for_kind(DocumentKind.DOCX, out)
    assert re_extracted.text == "a < b & c > d \x1e"
