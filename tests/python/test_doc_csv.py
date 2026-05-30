"""CSV adapter — extract segments + redact_document round-trip.

Stdlib-only; no external dep, so no importorskip guard needed.
"""

from __future__ import annotations

import csv
import io

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.documents import DocumentKind, redact_document
from apii.documents._base import CsvCell
from apii.documents.csv import CELL_SEP, ROW_SEP, CsvAdapter


def _grid(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline="")))


def test_extract_cells_with_per_cell_segments():
    data = b"name,phone\nAhmed,0501234567\nWalid,0509876543\n"
    ex = CsvAdapter.extract(data)
    assert ex.kind is DocumentKind.CSV
    # 2 cells/row x 3 rows = 6 segments.
    assert len(ex.segments) == 6
    assert "Ahmed" in ex.text
    assert "0501234567" in ex.text

    # First segment maps to "name" at (0,0).
    s0 = ex.segments[0]
    start, end = s0.text_range
    assert ex.text[start:end] == "name"
    assert s0.source == CsvCell(row=0, col=0)

    # Every segment's range slices back to its exact cell text, and the
    # row/col indices advance as expected.
    rows = _grid(data.decode())
    flat = [(r, c, cell) for r, row in enumerate(rows) for c, cell in enumerate(row)]
    for seg, (row, col, cell) in zip(ex.segments, flat):
        s, e = seg.text_range
        assert ex.text[s:e] == cell
        assert seg.source == CsvCell(row=row, col=col)

    # Separators are present in the joined text.
    assert CELL_SEP in ex.text
    assert ROW_SEP in ex.text


def test_extract_with_pii_text_contains_phone_and_email():
    data = b"contact,value\nphone,0501234567\nemail,a@b.ae\n"
    ex = CsvAdapter.extract(data)
    assert "0501234567" in ex.text
    assert "a@b.ae" in ex.text
    assert len(ex.segments) == 6


def test_extract_rejects_invalid_utf8():
    import pytest

    with pytest.raises(Exception):
        CsvAdapter.extract(bytes([0xFF, 0xFE, 0xFD]))


def test_emit_re_quotes_cells_with_commas():
    data = b"a,b\nx,y\n"
    ex = CsvAdapter.extract(data)
    anonymized = ex.text.replace("y", "TOKEN,WITH,COMMAS")
    out = CsvAdapter.emit(data, ex, anonymized).decode()
    # csv writer must wrap the comma-bearing cell in quotes.
    assert '"TOKEN,WITH,COMMAS"' in out


def test_emit_preserves_ragged_rows():
    data = b"a,b,c\nx\np,q\n"
    ex = CsvAdapter.extract(data)
    out = CsvAdapter.emit(data, ex, ex.text).decode()
    assert _grid(out) == [["a", "b", "c"], ["x"], ["p", "q"]]


def test_emit_keeps_genuine_trailing_empty_cell():
    data = b"a,\nb,c\n"
    ex = CsvAdapter.extract(data)
    out = CsvAdapter.emit(data, ex, ex.text).decode()
    # "a," is row [a, ""]; the trailing empty cell must survive.
    assert _grid(out) == [["a", ""], ["b", "c"]]


def test_redact_document_round_trip_restores_original():
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    original = b"name,phone,email\nAhmed,0501234567,a@b.ae\nWalid,0509876543,c@d.ae\n"
    kind, out, report = redact_document(original, a, kind=DocumentKind.CSV)

    assert kind is DocumentKind.CSV
    redacted = out.decode()
    # PII removed, tokens spliced in.
    assert "0501234567" not in redacted
    assert "a@b.ae" not in redacted
    assert "PHONE_" in redacted
    assert "EMAIL_" in redacted
    # Structure preserved: same grid shape, headers intact.
    rgrid = _grid(redacted)
    assert rgrid[0] == ["name", "phone", "email"]
    assert len(rgrid) == 3
    assert all(len(r) == 3 for r in rgrid)

    # Deanonymizing the redacted file restores the original grid.
    assert _grid(a.deanonymize(redacted)) == _grid(original.decode())
