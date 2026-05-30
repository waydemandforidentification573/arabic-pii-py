"""Plain-text / markdown adapter.

The whole file is one segment; extract is identity, emit returns the
anonymized text verbatim. Also the safety net other adapters fall back to.
"""

from __future__ import annotations

from apii.documents._base import DocumentError, DocumentKind, ExtractedDoc


class PlainAdapter:
    @staticmethod
    def extract(data: bytes) -> ExtractedDoc:
        # Invalid UTF-8 is a loud parse error, not a guessed encoding —
        # re-encode legacy Windows-1256/CP1252 upstream.
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise DocumentError(f"invalid UTF-8: {e}") from e
        return ExtractedDoc.whole(DocumentKind.TXT, text)

    @staticmethod
    def emit(data: bytes, extracted: ExtractedDoc, anonymized: str) -> bytes:
        return anonymized.encode("utf-8")
