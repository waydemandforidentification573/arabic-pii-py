"""DOCX adapter.

DOCX is a ZIP of OOXML files; the text content lives in
``word/document.xml`` inside ``<w:t>...</w:t>`` elements. Each such
element is one "run" of text. Microsoft Word fragments a single sentence
across multiple runs when fonts, colours, or autocorrect markup change,
which means a PII span the user *typed* in one go can be split across N
runs in the source XML. We deliberately give up cross-run detection to
keep emit deterministic (the vast majority of real PII fits in one run):
run bodies are concatenated with a U+001E separator, a control char no
detector consumes and the anonymizer preserves verbatim, so it survives
tokenization and round-trips cleanly without a detection span crossing a
run boundary.

We never re-serialize the XML through an XML library: ElementTree would
rewrite ``<w:t>`` to ``<ns0:t>`` and could drop attributes Word relies
on. Instead a byte-range scanner edits only the bytes inside ``<w:t>``
element bodies. Headers, footers, comments, footnotes, tables,
hyperlinks, images, and every other DOCX feature round-trip unchanged.

Offsets are Python ``str`` CHAR indices into ``ExtractedDoc.text``
(end-exclusive). Each segment's ``text_range`` covers the run body
**only**, never the U+001E separator that follows it. Every run gets
``DocxRun(paragraph=0, run=<global run index>)`` — the whole document is
treated as one paragraph and runs are numbered globally in document
order. emit ignores the locator (it re-derives structure from the raw
bytes), so this is a back-pointer for callers, not load-bearing.
"""

from __future__ import annotations

import io
import zipfile
from typing import Iterator

from apii.documents._base import (
    DocumentError,
    DocumentKind,
    DocxRun,
    ExtractedDoc,
    Segment,
)

NODE_SEP = "\x1e"
DOCUMENT_XML = "word/document.xml"


def _scan_text_elements(src: str) -> Iterator[tuple[int, int]]:
    """Yield ``(body_start, body_end)`` char ranges for each
    ``<w:t>...</w:t>`` element body in ``src``.

    Handles namespace prefixes (``<w:t>``), attributes
    (``<w:t xml:space="preserve">``), and self-closing empty elements
    (skipped — no body). Lookalike tags such as ``<w:tab>``, ``<w:tbl>``,
    ``<w:tc>`` start with ``<w:t`` but are not text elements and are
    skipped: the char immediately after ``<w:t`` must be a space, ``>``,
    or ``/`` for the element to count as a text run.
    """
    n = len(src)
    pos = 0
    while pos < n:
        next_open = src.find("<w:t", pos)
        if next_open == -1:
            return
        after = next_open + 4
        if after >= n:
            return
        after_ch = src[after]
        if after_ch not in (" ", ">", "/"):
            # `<w:ta...`, `<w:tb...`, `<w:tc...` — not a text element.
            pos = next_open + 1
            continue
        open_end = src.find(">", after)
        if open_end == -1:
            return
        # Self-closing `<w:t .../>`
        if open_end > 0 and src[open_end - 1] == "/":
            pos = open_end + 1
            continue
        body_start = open_end + 1
        close_start = src.find("</w:t>", body_start)
        if close_start == -1:
            return
        yield (body_start, close_start)
        pos = close_start + 6  # len("</w:t>")


def _xml_unescape(s: str) -> str:
    """Decode the five XML predefined entities (&amp; &lt; &gt; &quot;
    &apos;) plus numeric character references. Anything we don't
    recognise is passed through verbatim."""
    out: list[str] = []
    rest = s
    while rest:
        amp_idx = rest.find("&")
        if amp_idx == -1:
            out.append(rest)
            break
        out.append(rest[:amp_idx])
        after_amp = rest[amp_idx:]
        semi = after_amp.find(";")
        if semi != -1:
            entity = after_amp[1:semi]
            replacement: str | None = None
            if entity == "amp":
                replacement = "&"
            elif entity == "lt":
                replacement = "<"
            elif entity == "gt":
                replacement = ">"
            elif entity == "quot":
                replacement = '"'
            elif entity == "apos":
                replacement = "'"
            elif entity[:2] in ("#x", "#X"):
                try:
                    cp = int(entity[2:], 16)
                    replacement = chr(cp)
                except (ValueError, OverflowError):
                    replacement = None
            elif entity[:1] == "#":
                try:
                    cp = int(entity[1:], 10)
                    replacement = chr(cp)
                except (ValueError, OverflowError):
                    replacement = None
            if replacement is not None:
                out.append(replacement)
                rest = after_amp[semi + 1 :]
                continue
        # Unrecognised entity — keep the `&` literal and move on.
        out.append("&")
        rest = after_amp[1:]
    return "".join(out)


def _xml_escape(s: str) -> str:
    """Escape the five XML special characters."""
    out: list[str] = []
    for c in s:
        if c == "&":
            out.append("&amp;")
        elif c == "<":
            out.append("&lt;")
        elif c == ">":
            out.append("&gt;")
        elif c == '"':
            out.append("&quot;")
        elif c == "'":
            out.append("&apos;")
        else:
            out.append(c)
    return "".join(out)


def _read_document_xml(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            try:
                raw = zf.read(DOCUMENT_XML)
            except KeyError as e:
                raise DocumentError(f"missing {DOCUMENT_XML}: {e}") from e
    except DocumentError:
        raise
    except (zipfile.BadZipFile, OSError) as e:
        raise DocumentError(f"zip open: {e}") from e
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise DocumentError(f"read {DOCUMENT_XML}: {e}") from e


class DocxAdapter:
    @staticmethod
    def extract(data: bytes) -> ExtractedDoc:
        doc_xml = _read_document_xml(data)
        parts: list[str] = []
        segments: list[Segment] = []
        cursor = 0  # char offset into the concatenated detector text
        run_idx = 0
        for body_start, body_end in _scan_text_elements(doc_xml):
            decoded = _xml_unescape(doc_xml[body_start:body_end])
            if not decoded:
                run_idx += 1
                continue
            start = cursor
            parts.append(decoded)
            cursor += len(decoded)
            end = cursor
            parts.append(NODE_SEP)
            cursor += 1
            segments.append(
                Segment(
                    text_range=(start, end),
                    source=DocxRun(paragraph=0, run=run_idx),
                )
            )
            run_idx += 1

        return ExtractedDoc(
            kind=DocumentKind.DOCX,
            text="".join(parts),
            segments=segments,
        )

    @staticmethod
    def emit(data: bytes, extracted: ExtractedDoc, anonymized: str) -> bytes:
        doc_xml = _read_document_xml(data)
        runs = list(_scan_text_elements(doc_xml))
        # We pushed a NODE_SEP after every NON-EMPTY decoded body and
        # skipped empty ones. Mirror that filter so leaf count lines up.
        nonempty = [
            (bs, be)
            for (bs, be) in runs
            if _xml_unescape(doc_xml[bs:be]) != ""
        ]
        # Split the anonymized text into per-run leaves: strip all trailing
        # separators, split on the separator, keep non-empty leaves always
        # and empty leaves only when there are no non-empty runs at all.
        trimmed = anonymized.rstrip(NODE_SEP)
        leaves = [
            leaf
            for leaf in trimmed.split(NODE_SEP)
            if leaf != "" or not nonempty
        ]

        if len(leaves) != len(nonempty):
            raise DocumentError(
                f"run count mismatch on emit: {len(leaves)} leaves vs "
                f"{len(nonempty)} non-empty runs"
            )

        # Map each non-empty run's body-start to its anonymized leaf, then
        # walk the source once, splicing escaped leaves into matching
        # bodies and copying empty bodies verbatim.
        leaf_by_start = {bs: leaf for (bs, _be), leaf in zip(nonempty, leaves)}

        out_parts: list[str] = []
        cursor = 0
        for body_start, body_end in runs:
            out_parts.append(doc_xml[cursor:body_start])
            leaf = leaf_by_start.get(body_start)
            if leaf is not None:
                out_parts.append(_xml_escape(leaf))
            else:
                out_parts.append(doc_xml[body_start:body_end])
            cursor = body_end
        out_parts.append(doc_xml[cursor:])
        new_xml = "".join(out_parts)

        return _write_zip_replacing_document(data, new_xml)


def _write_zip_replacing_document(data: bytes, new_document_xml: str) -> bytes:
    try:
        src = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as e:
        raise DocumentError(f"zip open: {e}") from e
    out_buf = io.BytesIO()
    try:
        with src, zipfile.ZipFile(out_buf, "w") as dst:
            for info in src.infolist():
                # Preserve the original compression method per entry.
                method = info.compress_type
                if info.filename == DOCUMENT_XML:
                    payload = new_document_xml.encode("utf-8")
                else:
                    payload = src.read(info.filename)
                # Re-use the original ZipInfo so name, date, and external
                # attributes survive; reset header/CRC bookkeeping via a
                # fresh writestr against a copy of the info.
                new_info = zipfile.ZipInfo(
                    filename=info.filename, date_time=info.date_time
                )
                new_info.compress_type = method
                new_info.external_attr = info.external_attr
                new_info.internal_attr = info.internal_attr
                new_info.create_system = info.create_system
                dst.writestr(new_info, payload)
    except DocumentError:
        raise
    except (zipfile.BadZipFile, OSError) as e:
        raise DocumentError(f"zip finalise: {e}") from e
    return out_buf.getvalue()
