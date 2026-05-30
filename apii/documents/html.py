"""HTML adapter.

Pulls text nodes out of the document and concatenates them into a
detector view; emits by splicing the anonymized text back into the
original character stream at the recorded ranges. Markup, attributes,
doctypes, scripts, and styles all round-trip unchanged.

Implementation strategy
-----------------------
A one-pass state machine over the input string (char indices, matching
the rest of ``apii``). It tracks whether the cursor is inside a tag,
inside a comment / CDATA / DOCTYPE, or inside ``<script>`` / ``<style>``
(where text content is NOT prose and must NOT be passed to the
detector). Text runs outside any of those zones are collected with
their char ranges; ``emit`` walks the source forward, substituting each
text-node range with its masked replacement.

Why not ``html.parser.HTMLParser``?
-----------------------------------
The stdlib ``HTMLParser`` is unsuitable here for two reasons:

1. With ``convert_charrefs=False`` it splits a single text-between-tags
   run into multiple ``handle_data`` / ``handle_entityref`` events
   (e.g. ``"Phone &amp; x"`` becomes three events). That breaks the
   "one segment per text node" granularity and would let a detection
   span cross an entity. With ``convert_charrefs=True`` it decodes
   entities, so the captured text no longer matches the raw source
   bytes and the splice would corrupt the file.
2. ``HTMLParser`` exposes only ``getpos()`` (line/column), not exact
   source offsets for data, so re-splicing the original byte stream
   requires fragile line-offset bookkeeping.

The state machine gives exact segment granularity, exact raw-slice
re-splicing, and full script / style / comment / DOCTYPE / CDATA
handling — all on stdlib only (no lxml).

The emit contract
-----------------
``extract`` joins text nodes with an ASCII record separator (``\\x1E``);
no PII regex matches it, so a detection span can never cross a
text-node boundary. ``emit`` re-splits the ``anonymized`` text on that
same separator: each leaf is the (possibly token-substituted) content
of one text node. The leaf count must equal the text-node count, or
the anonymized text was mangled and we raise ``DocumentError``. The
output is rebuilt by walking the original source forward, copying the
inter-node markup verbatim and substituting each node's leaf.
"""

from __future__ import annotations

from dataclasses import dataclass

from apii.documents._base import (
    DocumentError,
    DocumentKind,
    ExtractedDoc,
    HtmlTextNode,
    Segment,
)

# Inter-text-node separator in the detector-view text. ASCII record
# separator — no PII regex matches it, so detection spans cannot cross
# a text-node boundary.
NODE_SEP = "\x1e"


@dataclass(frozen=True)
class _TextNode:
    """A run of prose text between tags, as a char range into the source."""

    start: int
    end: int


# ── scan states ──
_TEXT = "text"
_IN_TAG = "in_tag"
_IN_COMMENT = "in_comment"
_IN_DOCTYPE = "in_doctype"
_IN_CDATA = "in_cdata"
_IN_SKIPPED = "in_skipped"  # inside <script>/<style> content

_SKIP_NONE = "none"
_SKIP_SCRIPT = "script"
_SKIP_STYLE = "style"


def _matches_ci(s: str, pos: int, needle: str) -> bool:
    """Case-insensitive prefix match of `needle` at `s[pos:]`."""
    end = pos + len(needle)
    if end > len(s):
        return False
    return s[pos:end].lower() == needle.lower()


def _find_at(s: str, pos: int, needle: str) -> bool:
    """Exact (case-sensitive) prefix match of `needle` at `s[pos:]`."""
    end = pos + len(needle)
    if end > len(s):
        return False
    return s[pos:end] == needle


def _classify_tag_open(s: str, pos: int) -> tuple[str, str]:
    """At a `<`, decide the next scan state. Returns (state, skip_kind)."""
    if _find_at(s, pos, "<!--"):
        return _IN_COMMENT, _SKIP_NONE
    if _matches_ci(s, pos, "<!doctype"):
        return _IN_DOCTYPE, _SKIP_NONE
    if _find_at(s, pos, "<![CDATA["):
        return _IN_CDATA, _SKIP_NONE
    if _matches_ci(s, pos, "<script"):
        return _IN_TAG, _SKIP_SCRIPT
    if _matches_ci(s, pos, "<style"):
        return _IN_TAG, _SKIP_STYLE
    return _IN_TAG, _SKIP_NONE


def _scan_text_nodes(s: str) -> list[_TextNode]:
    """One-pass state machine yielding every prose text-node char range
    outside of tags, comments, DOCTYPE, CDATA, <script>, and <style>
    blocks. Ranges are char offsets into `s`."""
    nodes: list[_TextNode] = []
    n = len(s)
    pos = 0
    state = _TEXT
    text_start = 0
    skip_kind = _SKIP_NONE

    while pos <= n:
        if state == _TEXT:
            if pos == n:
                if text_start < pos:
                    nodes.append(_TextNode(text_start, pos))
                break
            if s[pos] == "<":
                text_end = pos
                next_state, skip_kind = _classify_tag_open(s, pos)
                if text_end > text_start:
                    nodes.append(_TextNode(text_start, text_end))
                state = next_state
                # pos stays put; classify only set the state.
            else:
                pos += 1

        elif state == _IN_TAG:
            if pos >= n:
                break
            c = s[pos]
            if c == '"' or c == "'":
                quote = c
                pos += 1
                while pos < n and s[pos] != quote:
                    pos += 1
                if pos < n:
                    pos += 1  # consume closing quote
            elif c == ">":
                pos += 1
                if skip_kind in (_SKIP_SCRIPT, _SKIP_STYLE):
                    state = _IN_SKIPPED
                else:
                    state = _TEXT
                    text_start = pos
            else:
                pos += 1

        elif state == _IN_COMMENT:
            if _find_at(s, pos, "-->"):
                pos += 3
                state = _TEXT
                text_start = pos
            elif pos < n:
                pos += 1
            else:
                break

        elif state == _IN_DOCTYPE:
            if pos < n and s[pos] == ">":
                pos += 1
                state = _TEXT
                text_start = pos
            elif pos < n:
                pos += 1
            else:
                break

        elif state == _IN_CDATA:
            if _find_at(s, pos, "]]>"):
                pos += 3
                state = _TEXT
                text_start = pos
            elif pos < n:
                pos += 1
            else:
                break

        elif state == _IN_SKIPPED:
            needle = "</script" if skip_kind == _SKIP_SCRIPT else "</style"
            if _matches_ci(s, pos, needle):
                pos += len(needle)
                while pos < n and s[pos] != ">":
                    pos += 1
                if pos < n:
                    pos += 1  # consume '>'
                state = _TEXT
                text_start = pos
            elif pos < n:
                pos += 1
            else:
                break

    return nodes


class HtmlAdapter:
    @staticmethod
    def extract(data: bytes) -> ExtractedDoc:
        try:
            s = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise DocumentError(f"invalid UTF-8: {e}") from e

        text_parts: list[str] = []
        segments: list[Segment] = []
        cursor = 0  # running length of the joined detector view
        node_index = 0

        for node in _scan_text_nodes(s):
            body = s[node.start : node.end]
            if not body:
                continue
            start = cursor
            text_parts.append(body)
            cursor += len(body)
            end = cursor
            text_parts.append(NODE_SEP)
            cursor += len(NODE_SEP)
            segments.append(
                Segment(text_range=(start, end), source=HtmlTextNode(node_index))
            )
            node_index += 1

        return ExtractedDoc(
            kind=DocumentKind.HTML,
            text="".join(text_parts),
            segments=segments,
        )

    @staticmethod
    def emit(data: bytes, extracted: ExtractedDoc, anonymized: str) -> bytes:
        try:
            s = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise DocumentError(f"invalid UTF-8: {e}") from e

        # Re-split the anonymized text on the separator used at extract
        # time, trimming a single trailing separator from the extract
        # step. A non-empty view always ends in one separator with no
        # adjacent separators (markup always sits between two text nodes),
        # so this yields exactly one leaf per text node. An empty view
        # splits to [""] (one leaf) and — with zero text nodes — trips the
        # count check below, raising DocumentError on an empty /
        # prose-less document.
        body = anonymized
        if body.endswith(NODE_SEP):
            body = body[: -len(NODE_SEP)]
        leaves = body.split(NODE_SEP)

        nodes = _scan_text_nodes(s)
        # Drop empty source nodes the same way extract did, so leaf and
        # node counts line up.
        nodes = [node for node in nodes if node.end > node.start]

        if len(leaves) != len(nodes):
            raise DocumentError(
                "text-node count mismatch on emit: "
                f"{len(leaves)} leaves vs {len(nodes)} nodes"
            )

        # Walk the source forward, substituting each text-node range with
        # its masked replacement. Forward is safe because we emit fresh
        # output; no in-place editing.
        out_parts: list[str] = []
        cursor = 0
        for node, leaf in zip(nodes, leaves):
            out_parts.append(s[cursor : node.start])
            out_parts.append(leaf)
            cursor = node.end
        out_parts.append(s[cursor:])
        return "".join(out_parts).encode("utf-8")
