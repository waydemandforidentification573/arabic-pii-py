"""PDF adapter — text-only output.

The round-trip is one-way: the source PDF is text-extracted, the detector
runs over the extracted text, and the masked output is plain UTF-8 text
(`.txt`). apii does not edit the PDF in place (rewriting the content
stream to preserve the original file structure) —
`DocumentKind.PDF.output_extension()` reports ``"txt"`` and
``preserves_layout()`` is ``False``.

pypdf exposes text per page, so we emit one `Segment` per page tagged
with `PdfPage(page)` (1-based). Page texts are concatenated into
`ExtractedDoc.text` with a form-feed (``\f``) separator between pages —
the conventional ASCII page break, which no PII recognizer tokenizes and
which therefore survives the anonymize → deanonymize round-trip byte for
byte. Char offsets in each `Segment.text_range` index into the joined
`ExtractedDoc.text` (end-exclusive).

emit flattens to `.txt` and returns `anonymized` as UTF-8 bytes — no
structural PDF rewrite. The per-page segment map is informational (it lets
the UI/caller report page boundaries). The page-separator form-feeds
inside `anonymized` are preserved unchanged, so a downstream
`deanonymize(out.decode())` restores the original joined text verbatim.

Extraction requires the optional `pypdf` dependency. If it is not
installed, `extract()` raises a `DocumentError` telling the operator to
`pip install apii[documents]`.
"""

from __future__ import annotations

import io

from apii.documents._base import (
    DocumentError,
    DocumentKind,
    ExtractedDoc,
    PdfPage,
    Segment,
)

# Separator placed between page texts in the concatenated extract. The
# ASCII form feed is the conventional page break: recognizers leave it
# alone, so it survives the anonymize/deanonymize round-trip and marks
# page boundaries for any consumer that wants to re-split the output.
_PAGE_SEP = "\f"


class PdfAdapter:
    @staticmethod
    def extract(data: bytes) -> ExtractedDoc:
        try:
            from pypdf import PdfReader
        except ImportError as e:  # pragma: no cover - exercised when dep absent
            raise DocumentError(
                "PDF support requires the optional 'pypdf' dependency; "
                "install it with `pip install apii[documents]`"
            ) from e

        # Any failure parsing the PDF or pulling text off a page is a loud
        # parse error.
        try:
            reader = PdfReader(io.BytesIO(data))
            page_texts = [page.extract_text() or "" for page in reader.pages]
        except DocumentError:
            raise
        except Exception as e:
            raise DocumentError(f"pdf-extract: {e}") from e

        parts: list[str] = []
        segments: list[Segment] = []
        cursor = 0
        for index, page_text in enumerate(page_texts):
            if index > 0:
                # The separator belongs to no page; advance past it.
                cursor += len(_PAGE_SEP)
                parts.append(_PAGE_SEP)
            start = cursor
            end = start + len(page_text)
            segments.append(Segment((start, end), PdfPage(page=index + 1)))
            parts.append(page_text)
            cursor = end

        text = "".join(parts)
        return ExtractedDoc(kind=DocumentKind.PDF, text=text, segments=segments)

    @staticmethod
    def emit(data: bytes, extracted: ExtractedDoc, anonymized: str) -> bytes:
        # Text-only output. PDF flattens to a `.txt` file, so emit returns
        # the anonymized text as UTF-8 bytes. The per-page form-feed
        # separators inside `anonymized` are left intact, keeping the
        # redact → deanonymize round-trip lossless.
        return anonymized.encode("utf-8")
