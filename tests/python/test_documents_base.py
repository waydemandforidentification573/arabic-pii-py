"""Document base: kind detection + plain adapter + redact_document flow."""

from __future__ import annotations

import pytest

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.documents import DocumentKind, extract_for_kind, redact_document
from apii.documents._base import Whole


def test_kind_from_extension():
    assert DocumentKind.from_extension("TXT") is DocumentKind.TXT
    assert DocumentKind.from_extension("markdown") is DocumentKind.MD
    assert DocumentKind.from_extension("docx") is DocumentKind.DOCX
    assert DocumentKind.from_extension("png") is None


def test_kind_from_magic_bytes():
    assert DocumentKind.from_bytes(b"%PDF-1.7\n...") is DocumentKind.PDF
    assert DocumentKind.from_bytes(b"<!DOCTYPE html><html>") is DocumentKind.HTML
    assert DocumentKind.from_bytes(b"<html lang=\"ar\">") is DocumentKind.HTML
    assert DocumentKind.from_bytes(b"  {\"a\":1}") is DocumentKind.JSON
    assert DocumentKind.from_bytes(b"\n[1,2]") is DocumentKind.JSON
    assert DocumentKind.from_bytes(b"hello, world") is DocumentKind.TXT
    assert DocumentKind.from_bytes(b"PK\x03\x04...word/document.xml") is DocumentKind.DOCX
    assert DocumentKind.from_bytes(b"PK\x03\x04...xl/workbook.xml") is DocumentKind.XLSX


def test_output_extension_and_layout():
    assert DocumentKind.PDF.output_extension() == "txt"
    assert DocumentKind.DOCX.output_extension() == "docx"
    assert not DocumentKind.PDF.preserves_layout()
    assert DocumentKind.HTML.preserves_layout()


def test_plain_extract_round_trip():
    original = "Customer: محمد العتيبي. Phone: 0501234567."
    ex = extract_for_kind(DocumentKind.TXT, original.encode())
    assert ex.text == original
    assert len(ex.segments) == 1
    assert ex.segments[0].text_range == (0, len(original))
    assert isinstance(ex.segments[0].source, Whole)


def test_plain_rejects_invalid_utf8():
    with pytest.raises(Exception):
        extract_for_kind(DocumentKind.TXT, bytes([0xFF, 0xFE, 0xFD]))


def test_redact_document_plain_anonymizes_and_round_trips():
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    data = "Phone 0501234567 email a@b.ae".encode()
    kind, out, report = redact_document(data, a, kind=DocumentKind.TXT)
    assert kind is DocumentKind.TXT
    redacted = out.decode()
    assert "0501234567" not in redacted and "a@b.ae" not in redacted
    assert "PHONE_" in redacted and "EMAIL_" in redacted
    # restore from the same anonymizer's vault
    assert a.deanonymize(redacted) == "Phone 0501234567 email a@b.ae"
