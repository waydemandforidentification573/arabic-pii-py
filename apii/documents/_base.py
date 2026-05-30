"""Shared document model.

The detector core works on plain text. This layer wraps it with per-format
adapters that (1) extract text + a back-pointer from each char range to its
source location, and (2) re-emit the file with detected spans replaced by
tokens, preserving structure where the format allows.

Offsets are Python str CHAR indices (the apii engine is char-based throughout).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol


class DocumentKind(enum.Enum):
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    JSON = "json"
    HTML = "html"
    DOCX = "docx"
    XLSX = "xlsx"
    PDF = "pdf"

    @classmethod
    def from_extension(cls, ext: str) -> "DocumentKind | None":
        return {
            "txt": cls.TXT, "md": cls.MD, "markdown": cls.MD, "csv": cls.CSV,
            "json": cls.JSON, "html": cls.HTML, "htm": cls.HTML,
            "docx": cls.DOCX, "xlsx": cls.XLSX, "pdf": cls.PDF,
        }.get(ext.lower())

    @classmethod
    def from_bytes(cls, data: bytes) -> "DocumentKind":
        """Magic-byte sniff; falls back to TXT."""
        if data.startswith(b"%PDF-"):
            return cls.PDF
        if data.startswith(b"PK\x03\x04"):
            window = data[:4096]
            if b"word/" in window:
                return cls.DOCX
            if b"xl/" in window:
                return cls.XLSX
        head = bytes(data[:64]).decode("latin-1").lower()
        if "<!doctype html" in head or "<html" in head:
            return cls.HTML
        # Strip only space/tab/newline/CR/FF — NOT 0x0B vertical tab — so a
        # leading VT before a brace is classified TXT, not JSON.
        stripped = data.lstrip(b" \t\n\x0c\r")
        if stripped[:1] in (b"{", b"["):
            return cls.JSON
        return cls.TXT

    def output_extension(self) -> str:
        # PDF flattens to txt (apii redacts PDFs to plain text, not in place).
        return "txt" if self is DocumentKind.PDF else self.value

    def preserves_layout(self) -> bool:
        return self is not DocumentKind.PDF


# ── source back-pointers ──

@dataclass(frozen=True)
class Whole:
    """Whole-file plain-text doc — one segment."""


@dataclass(frozen=True)
class CsvCell:
    row: int
    col: int


@dataclass(frozen=True)
class JsonPath:
    path: str  # pointer-style, e.g. /items/3/name


@dataclass(frozen=True)
class HtmlTextNode:
    index: int


@dataclass(frozen=True)
class DocxRun:
    paragraph: int
    run: int


@dataclass(frozen=True)
class XlsxCell:
    sheet: str
    row: int
    col: int


@dataclass(frozen=True)
class PdfPage:
    page: int


SourceLocator = (
    Whole | CsvCell | JsonPath | HtmlTextNode | DocxRun | XlsxCell | PdfPage
)


@dataclass(frozen=True)
class Segment:
    """A chunk of extracted text + where it came from. `text_range` is a
    (start, end) char range into ExtractedDoc.text (end exclusive)."""

    text_range: tuple[int, int]
    source: SourceLocator


@dataclass
class ExtractedDoc:
    kind: DocumentKind
    text: str
    segments: list[Segment] = field(default_factory=list)

    @classmethod
    def whole(cls, kind: DocumentKind, text: str) -> "ExtractedDoc":
        return cls(kind=kind, text=text, segments=[Segment((0, len(text)), Whole())])


class DocumentError(Exception):
    pass


class DocumentAdapter(Protocol):
    """Per-format adapter. extract: bytes → text + source map; emit:
    original bytes + extracted + anonymized text → new file bytes."""

    @staticmethod
    def extract(data: bytes) -> ExtractedDoc: ...

    @staticmethod
    def emit(data: bytes, extracted: ExtractedDoc, anonymized: str) -> bytes: ...
