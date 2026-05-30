"""XLSX adapter.

XLSX stores cell text two ways:
  - inline strings: ``<is><t>VALUE</t></is>`` directly inside a cell
  - shared strings: ``<sst><si><t>VALUE</t></si></sst>`` in
    ``xl/sharedStrings.xml``, referenced by cells via ``<c t="s"><v>N</v></c>``
    where N is the 0-based index into the shared-string table.

For both, the textual content lives inside ``<t>...</t>`` elements. As in
the DOCX adapter, we find every ``<t>`` body across every text-bearing
``xl/*.xml`` part (``sharedStrings.xml`` + every worksheet) and treat
each as a segment. Bodies are concatenated into the detector view in a
deterministic order (sharedStrings first, then worksheets sorted by name)
separated by U+001E (RECORD SEPARATOR).

Why re-splitting on U+001E is safe: the separator is a control character
that no PII recognizer matches, and tokens are only spliced into detected
spans (never across a separator), so the U+001E delimiters survive the
anonymizer untouched and the leaf count is preserved. emit raises
DocumentError if that invariant is ever violated (leaf/element mismatch).

Offsets in ExtractedDoc.text are Python str CHAR indices (end-exclusive).

stdlib only — ``zipfile`` for the OOXML package, manual ``<t>`` scanning:
ElementTree would rewrite/normalize the XML and break the byte-identical
round-trip of untouched parts.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from apii.documents._base import (
    DocumentError,
    DocumentKind,
    ExtractedDoc,
    Segment,
    XlsxCell,
)

NODE_SEP = "\x1e"


class XlsxAdapter:
    @staticmethod
    def extract(data: bytes) -> ExtractedDoc:
        parts = _collect_text_parts(data)
        text_pieces: list[str] = []
        segments: list[Segment] = []
        cursor = 0
        cell_idx = 0
        for part_name, body in parts:
            for elem in _scan_t_elements(body):
                decoded = _xml_unescape(body[elem.start : elem.end])
                if not decoded:
                    continue
                start = cursor
                text_pieces.append(decoded)
                cursor += len(decoded)
                end = cursor
                # separator after each cell so detection can't cross cells
                text_pieces.append(NODE_SEP)
                cursor += 1
                segments.append(
                    Segment(
                        text_range=(start, end),
                        source=XlsxCell(sheet=part_name, row=0, col=cell_idx),
                    )
                )
                cell_idx += 1
        return ExtractedDoc(
            kind=DocumentKind.XLSX,
            text="".join(text_pieces),
            segments=segments,
        )

    @staticmethod
    def emit(data: bytes, extracted: ExtractedDoc, anonymized: str) -> bytes:
        parts = _collect_text_parts(data)
        # All non-empty <t> elements, in the same order extract used.
        all_elems: list[tuple[str, _TElem]] = []
        for part_name, body in parts:
            for e in _scan_t_elements(body):
                if _xml_unescape(body[e.start : e.end]):
                    all_elems.append((part_name, e))

        leaves = anonymized.rstrip(NODE_SEP).split(NODE_SEP) if anonymized else []
        # An all-separator / empty view yields no leaves; align with element count.
        if not all_elems:
            leaves = []
        if len(leaves) != len(all_elems):
            raise DocumentError(
                f"parse {DocumentKind.XLSX}: <t> element count mismatch on emit: "
                f"{len(leaves)} leaves vs {len(all_elems)} elements"
            )

        # Group leaves by part so each XML file is rewritten once.
        groups: dict[str, list[tuple[_TElem, str]]] = {}
        for (part_name, e), leaf in zip(all_elems, leaves):
            groups.setdefault(part_name, []).append((e, leaf))

        rewritten: dict[str, str] = {}
        for part_name, original_body in parts:
            group = sorted(groups.get(part_name, []), key=lambda pair: pair[0].start)
            out_chunks: list[str] = []
            cur = 0
            for e, leaf in group:
                out_chunks.append(original_body[cur : e.start])
                out_chunks.append(_xml_escape(leaf))
                cur = e.end
            out_chunks.append(original_body[cur:])
            rewritten[part_name] = "".join(out_chunks)

        return _write_zip_replacing_parts(data, rewritten)


# ── zip / part collection ──


def _collect_text_parts(data: bytes) -> list[tuple[str, str]]:
    """Pull every text-bearing XML part out of the zip, as
    ``(part_name, body)`` in deterministic order: sharedStrings first
    (Excel's string pool), then worksheets sorted by name."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as e:
        raise DocumentError(f"parse {DocumentKind.XLSX}: zip open: {e}") from e
    try:
        names = [
            n
            for n in zf.namelist()
            if n == "xl/sharedStrings.xml" or n.startswith("xl/worksheets/sheet")
        ]
        names.sort(key=lambda n: (0 if n == "xl/sharedStrings.xml" else 1, n))
        out: list[tuple[str, str]] = []
        for name in names:
            try:
                raw = zf.read(name)
            except KeyError as e:
                raise DocumentError(
                    f"parse {DocumentKind.XLSX}: missing {name}: {e}"
                ) from e
            try:
                body = raw.decode("utf-8")
            except UnicodeDecodeError as e:
                raise DocumentError(
                    f"parse {DocumentKind.XLSX}: read {name}: {e}"
                ) from e
            out.append((name, body))
        return out
    finally:
        zf.close()


def _write_zip_replacing_parts(data: bytes, rewritten: dict[str, str]) -> bytes:
    """Copy every zip entry through, replacing the bodies in `rewritten`
    and leaving everything else byte-identical (same compression)."""
    try:
        src = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as e:
        raise DocumentError(f"parse {DocumentKind.XLSX}: zip open: {e}") from e
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as dst:
            for info in src.infolist():
                name = info.filename
                if name in rewritten:
                    payload = rewritten[name].encode("utf-8")
                else:
                    payload = src.read(name)
                # Preserve each entry's original compression method.
                out_info = zipfile.ZipInfo(filename=name, date_time=info.date_time)
                out_info.compress_type = info.compress_type
                out_info.external_attr = info.external_attr
                out_info.internal_attr = info.internal_attr
                out_info.create_system = info.create_system
                dst.writestr(out_info, payload)
        return buf.getvalue()
    finally:
        src.close()


# ── <t> element scanning ──


@dataclass
class _TElem:
    start: int  # char index of body start (inclusive)
    end: int  # char index of body end (exclusive)


def _scan_t_elements(src: str) -> list[_TElem]:
    """Scan an XML string for every ``<t...>BODY</t>`` element. Matches
    the unprefixed ``<t>`` form used by the XLSX schema; the next char
    after ``<t`` must be space, ``>`` or ``/``. Self-closing ``<t/>`` is
    skipped. Operates on CHAR indices (Python-native)."""
    out: list[_TElem] = []
    n = len(src)
    pos = 0
    while pos < n:
        open_idx = src.find("<t", pos)
        if open_idx == -1:
            break
        after = open_idx + 2
        if after >= n:
            break
        after_c = src[after]
        if after_c not in (" ", ">", "/"):
            pos = open_idx + 1
            continue
        close_of_open = src.find(">", after)
        if close_of_open == -1:
            break
        # Self-closing <t .../>
        if close_of_open > 0 and src[close_of_open - 1] == "/":
            pos = close_of_open + 1
            continue
        body_start = close_of_open + 1
        close_start = src.find("</t>", body_start)
        if close_start == -1:
            break
        out.append(_TElem(start=body_start, end=close_start))
        pos = close_start + 4
    return out


# ── OOXML entity (un)escaping ──


def _xml_unescape(s: str) -> str:
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        amp = s.find("&", i)
        if amp == -1:
            out.append(s[i:])
            break
        out.append(s[i:amp])
        semi = s.find(";", amp)
        replacement = None
        if semi != -1:
            entity = s[amp + 1 : semi]
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
                    cp = int(entity[1:])
                    replacement = chr(cp)
                except (ValueError, OverflowError):
                    replacement = None
        if replacement is not None:
            out.append(replacement)
            i = semi + 1
            continue
        # Unrecognised entity — keep the `&` literal and move on.
        out.append("&")
        i = amp + 1
    return "".join(out)


def _xml_escape(s: str) -> str:
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
