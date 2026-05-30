"""CSV adapter.

`extract` pulls every cell and concatenates them into the detector-view
`text` with two ASCII control characters as separators:

    * U+001F (unit separator)   between cells within a row
    * U+001E (record separator) between rows

No PII regex matches either control char, so a detection span can't
accidentally cross a cell or row boundary even when adjacent cells hold
similar content. One ``Segment`` is emitted per cell, carrying a
``CsvCell(row, col)`` back-pointer.

`emit` ignores the per-segment ranges and instead re-splits the
*anonymized* string on the very same separators the extract step
inserted. This avoids per-segment offset bookkeeping and tolerates token
substitution shifting ranges arbitrarily (a token is never the same
length as the PII it replaces). The separators survive the anonymizer
untouched — they are not matched by any recognizer and the anonymizer
only splices tokens into the original text — so the split recovers the
exact grid shape. The grid is then re-serialized with the stdlib ``csv``
writer, which re-quotes any cell whose anonymized content now contains a
comma/quote/newline.

Assumes comma-separated UTF-8 input (the stdlib ``csv`` module handles
quoting / escaping). Non-UTF-8 input fails at extract time with a clear
``DocumentError``. Flexible/ragged rows (varying field counts, common in
CRM exports) are tolerated on both extract and emit. Stdlib only — no
external dependency.
"""

from __future__ import annotations

import csv
import io

from apii.documents._base import (
    CsvCell,
    DocumentError,
    DocumentKind,
    ExtractedDoc,
    Segment,
)

# Inter-cell and inter-row separators in the detector-view text. Both are
# ASCII control characters that no PII regex matches.
CELL_SEP = "\x1f"  # unit separator
ROW_SEP = "\x1e"  # record separator


class CsvAdapter:
    @staticmethod
    def extract(data: bytes) -> ExtractedDoc:
        try:
            decoded = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise DocumentError(f"parse csv: invalid UTF-8: {e}") from e

        # has_headers(false) + flexible: every row is data, ragged rows ok.
        reader = csv.reader(io.StringIO(decoded, newline=""))

        parts: list[str] = []
        segments: list[Segment] = []
        pos = 0
        try:
            for row_idx, record in enumerate(reader):
                for col_idx, cell in enumerate(record):
                    start = pos
                    parts.append(cell)
                    pos += len(cell)
                    end = pos
                    segments.append(
                        Segment(
                            text_range=(start, end),
                            source=CsvCell(row=row_idx, col=col_idx),
                        )
                    )
                    # Cell separator after every cell (incl. the last in a
                    # row — emit drops the resulting empty tail entry).
                    parts.append(CELL_SEP)
                    pos += len(CELL_SEP)
                parts.append(ROW_SEP)
                pos += len(ROW_SEP)
        except csv.Error as e:
            raise DocumentError(f"parse csv: {e}") from e

        return ExtractedDoc(
            kind=DocumentKind.CSV,
            text="".join(parts),
            segments=segments,
        )

    @staticmethod
    def emit(data: bytes, extracted: ExtractedDoc, anonymized: str) -> bytes:
        # Re-split the anonymized text on the same separators extract used.
        # Tolerant of token substitution shifting offsets arbitrarily.
        out = io.StringIO()
        # lineterminator="\n" keeps output byte-stable (the writer would
        # otherwise emit CRLF, breaking exact round-trip comparisons).
        writer = csv.writer(out, lineterminator="\n")

        trimmed = anonymized.rstrip(ROW_SEP)
        try:
            for row_block in trimmed.split(ROW_SEP):
                if row_block == "":
                    continue
                cells = row_block.split(CELL_SEP)
                # extract pushed a trailing CELL_SEP after the last cell;
                # drop exactly one resulting empty tail entry (a genuine
                # trailing empty cell like "a," must keep its real one).
                if cells and cells[-1] == "":
                    cells = cells[:-1]
                writer.writerow(cells)
        except csv.Error as e:
            raise DocumentError(f"parse csv: {e}") from e

        return out.getvalue().encode("utf-8")
