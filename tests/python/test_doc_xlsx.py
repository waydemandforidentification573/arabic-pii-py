"""XLSX adapter: extract segments + redact_document round-trip.

Builds a minimal but structurally valid .xlsx in-memory with zipfile
(no external dep), so the suite stays green on a stdlib-only install.
The adapter itself is stdlib-only; the importorskip guard is defensive.
"""

from __future__ import annotations

import io
import zipfile

import pytest

# Adapter is stdlib-only; guard defensively so the base suite never breaks
# if this module ever grows an optional dep.
xlsx_mod = pytest.importorskip("apii.documents.xlsx")

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.documents import DocumentKind, extract_for_kind, redact_document
from apii.documents._base import XlsxCell
from apii.documents.xlsx import NODE_SEP, XlsxAdapter

# Cell strings carried in the shared-string table. Includes PII (a Saudi
# mobile and an .ae email) plus benign labels and an XML-escaped value.
SHARED_STRINGS = [
    "Name",
    "Phone",
    "Email",
    "Contact 0501234567 here",
    "a@b.ae",
    "R&amp;D dept",  # escaped ampersand in the source XML
]


def _build_xlsx(shared: list[str]) -> bytes:
    """Assemble a minimal OOXML spreadsheet: one sheet whose cells all
    reference the shared-string table (t="s"), plus the parts Excel needs
    to consider the file well-formed."""
    sst_si = "".join(f"<si><t>{s}</t></si>" for s in shared)
    shared_strings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared)}" uniqueCount="{len(shared)}">{sst_si}</sst>'
    )
    # one row per shared string, single column A, all string refs
    rows = "".join(
        f'<row r="{i + 1}"><c r="A{i + 1}" t="s"><v>{i}</v></c></row>'
        for i in range(len(shared))
    )
    sheet1 = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{rows}</sheetData></worksheet>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/sharedStrings.xml", shared_strings)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1)
    return buf.getvalue()


def _build_xlsx_mixed() -> bytes:
    """A sheet with one shared-string cell and one inline-string cell, so
    both the sharedStrings part and the worksheet part carry a <t>. Proves
    the multi-part ordering and the global col counter."""
    shared_strings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'count="1" uniqueCount="1"><si><t>Email a@b.ae</t></si></sst>'
    )
    sheet1 = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>Call 0501234567 now</t></is></c></row>'
        "</sheetData></worksheet>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/sharedStrings.xml", shared_strings)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1)
    return buf.getvalue()


def test_magic_bytes_detect_xlsx():
    data = _build_xlsx(SHARED_STRINGS)
    assert DocumentKind.from_bytes(data) is DocumentKind.XLSX


def test_extract_text_and_segments():
    data = _build_xlsx(SHARED_STRINGS)
    ex = extract_for_kind(DocumentKind.XLSX, data)

    assert ex.kind is DocumentKind.XLSX
    # one segment per non-empty <t>; sharedStrings part only here
    assert len(ex.segments) == len(SHARED_STRINGS)
    assert all(isinstance(seg.source, XlsxCell) for seg in ex.segments)
    assert all(seg.source.sheet == "xl/sharedStrings.xml" for seg in ex.segments)
    assert [seg.source.col for seg in ex.segments] == list(range(len(SHARED_STRINGS)))

    # text is the unescaped bodies joined by U+001E, one trailing sep too
    expected_decoded = [
        "Name",
        "Phone",
        "Email",
        "Contact 0501234567 here",
        "a@b.ae",
        "R&D dept",  # &amp; decoded
    ]
    assert ex.text == NODE_SEP.join(expected_decoded) + NODE_SEP

    # each segment range slices to its decoded cell value
    for seg, want in zip(ex.segments, expected_decoded):
        s, e = seg.text_range
        assert ex.text[s:e] == want

    # the PII is present in the detector view
    assert "0501234567" in ex.text
    assert "a@b.ae" in ex.text


def test_extract_skips_empty_and_self_closing_t():
    # empty <t></t> (from the "" entry) and a hand-injected self-closing
    # <t/> must produce no segments; only the real cell survives.
    data = _build_xlsx(["", "Real value 0501234567"])
    # patch a self-closing <t/> into the shared-string XML to exercise that path
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        sst = zf.read("xl/sharedStrings.xml").decode("utf-8")
    sst = sst.replace("<si><t></t></si>", "<si><t/></si>", 1)
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w") as dst:
        for name in src.namelist():
            payload = sst.encode() if name == "xl/sharedStrings.xml" else src.read(name)
            dst.writestr(name, payload)
    data = buf.getvalue()

    ex = extract_for_kind(DocumentKind.XLSX, data)
    assert len(ex.segments) == 1
    assert ex.text == "Real value 0501234567" + NODE_SEP


def test_redact_document_round_trip():
    data = _build_xlsx(SHARED_STRINGS)
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    kind, out, report = redact_document(data, a, kind=DocumentKind.XLSX)

    assert kind is DocumentKind.XLSX
    # output is still a valid zip and a valid xlsx by magic bytes
    assert DocumentKind.from_bytes(out) is DocumentKind.XLSX
    with zipfile.ZipFile(io.BytesIO(out)) as zf:
        sst = zf.read("xl/sharedStrings.xml").decode("utf-8")

    # PII gone from the redacted shared strings, tokens spliced in
    assert "0501234567" not in sst
    assert "a@b.ae" not in sst
    assert "PHONE_" in sst
    assert "EMAIL_" in sst
    # untouched cells survive verbatim (escaped form preserved)
    assert "<t>Name</t>" in sst
    assert "R&amp;D dept" in sst

    # re-extract the redacted file and deanonymize its view → original view
    ex_orig = extract_for_kind(DocumentKind.XLSX, data)
    ex_red = extract_for_kind(DocumentKind.XLSX, out)
    assert a.deanonymize(ex_red.text) == ex_orig.text


def test_inline_string_worksheet_cell_and_global_col():
    # sharedStrings part contributes col 0; worksheet inline-str is col 1.
    data = _build_xlsx_mixed()
    ex = extract_for_kind(DocumentKind.XLSX, data)

    assert len(ex.segments) == 2
    # sharedStrings is ordered first, then the worksheet
    s0, s1 = ex.segments
    assert s0.source.sheet == "xl/sharedStrings.xml"
    assert s0.source.col == 0
    assert s1.source.sheet == "xl/worksheets/sheet1.xml"
    assert s1.source.col == 1  # global counter continues across parts

    assert ex.text == "Email a@b.ae" + NODE_SEP + "Call 0501234567 now" + NODE_SEP
    assert ex.text[s1.text_range[0] : s1.text_range[1]] == "Call 0501234567 now"

    # round-trip: redact then re-extract+deanonymize restores the view
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    _, out, _ = redact_document(data, a, kind=DocumentKind.XLSX)
    with zipfile.ZipFile(io.BytesIO(out)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        sst = zf.read("xl/sharedStrings.xml").decode("utf-8")
    # PII gone from both parts, tokens spliced into the right part
    assert "0501234567" not in sheet and "PHONE_" in sheet
    assert "a@b.ae" not in sst and "EMAIL_" in sst

    ex_red = extract_for_kind(DocumentKind.XLSX, out)
    assert a.deanonymize(ex_red.text) == ex.text


def test_emit_count_mismatch_raises():
    from apii.documents._base import DocumentError

    data = _build_xlsx(SHARED_STRINGS)
    ex = extract_for_kind(DocumentKind.XLSX, data)
    # an anonymized view with the wrong number of separators must error
    with pytest.raises(DocumentError):
        XlsxAdapter.emit(data, ex, "too few leaves" + NODE_SEP)


def test_extract_rejects_non_zip():
    from apii.documents._base import DocumentError

    with pytest.raises(DocumentError):
        XlsxAdapter.extract(b"not a zip at all")
