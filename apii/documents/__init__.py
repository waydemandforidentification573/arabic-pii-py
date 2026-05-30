"""Document-format ingestion and dispatch.

Pick an adapter by extension (then magic-bytes), extract text, run the
anonymizer on it, and emit a redacted file in the same format. Adapters
are lazily imported per kind so the heavy optional deps (python-docx,
openpyxl, lxml, pypdf) are only needed for the formats actually used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from apii.documents._base import (
    CsvCell,
    DocumentAdapter,
    DocumentError,
    DocumentKind,
    DocxRun,
    ExtractedDoc,
    HtmlTextNode,
    JsonPath,
    PdfPage,
    Segment,
    SourceLocator,
    Whole,
    XlsxCell,
)

__all__ = [
    "DocumentKind", "ExtractedDoc", "Segment", "SourceLocator", "DocumentError",
    "DocumentAdapter", "Whole", "CsvCell", "JsonPath", "HtmlTextNode", "DocxRun",
    "XlsxCell", "PdfPage", "extract_for_kind", "emit_for_kind", "extract_from_path",
    "redact_document",
]


def _adapter(kind: DocumentKind):
    """Lazy per-kind adapter import (keeps optional deps optional)."""
    if kind in (DocumentKind.TXT, DocumentKind.MD):
        from apii.documents.plain import PlainAdapter
        return PlainAdapter
    if kind is DocumentKind.CSV:
        from apii.documents.csv import CsvAdapter
        return CsvAdapter
    if kind is DocumentKind.JSON:
        from apii.documents.json import JsonAdapter
        return JsonAdapter
    if kind is DocumentKind.HTML:
        from apii.documents.html import HtmlAdapter
        return HtmlAdapter
    if kind is DocumentKind.DOCX:
        from apii.documents.docx import DocxAdapter
        return DocxAdapter
    if kind is DocumentKind.XLSX:
        from apii.documents.xlsx import XlsxAdapter
        return XlsxAdapter
    if kind is DocumentKind.PDF:
        from apii.documents.pdf import PdfAdapter
        return PdfAdapter
    raise DocumentError(f"unsupported format: {kind}")


def extract_for_kind(kind: DocumentKind, data: bytes) -> ExtractedDoc:
    return _adapter(kind).extract(data)


def emit_for_kind(kind: DocumentKind, data: bytes, extracted: ExtractedDoc, anonymized: str) -> bytes:
    return _adapter(kind).emit(data, extracted, anonymized)


def extract_from_path(path) -> tuple[DocumentKind, ExtractedDoc]:
    path = Path(path)
    data = path.read_bytes()
    kind = None
    if path.suffix:
        kind = DocumentKind.from_extension(path.suffix.lstrip("."))
    if kind is None:
        kind = DocumentKind.from_bytes(data)
    return kind, extract_for_kind(kind, data)


def redact_document(
    data: bytes, anonymizer, *, kind: Optional[DocumentKind] = None
) -> tuple[DocumentKind, bytes, object]:
    """Extract → anonymize the document's text → emit a redacted file.

    Returns (kind, output_bytes, AnonymizationReport). The anonymizer's
    vault is populated so the output can later be restored. `kind`
    defaults to magic-byte detection.
    """
    if kind is None:
        kind = DocumentKind.from_bytes(data)
    extracted = extract_for_kind(kind, data)
    report = anonymizer.anonymize(extracted.text)
    out = emit_for_kind(kind, data, extracted, report.text)
    return kind, out, report
