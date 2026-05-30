"""JSON adapter.

Walks the parsed value tree, concatenates every STRING LEAF into a
detector-view text joined by an ASCII record-separator (U+001E), and
records a Segment per leaf carrying its RFC-6901 JSON-pointer path
(e.g. ``/items/3/name``). Object KEYS are never touched — only string
*values* are PII candidates. Numbers, booleans, nulls, and keys
round-trip unchanged.

emit re-splices: detection runs on the concatenated ``ExtractedDoc.text``
and produces ``anonymized`` (tokens spliced in, possibly a different
length than the original). We re-parse the original bytes to clone the
structure, split ``anonymized`` on the same U+001E separator to recover
the per-leaf values in traversal order, then walk the tree again in
lockstep replacing each string leaf with the next recovered value, and
re-serialize. The separator survives tokenization because no recognizer
matches U+001E as part of an entity, so detection spans never cross a
leaf boundary — the split is exact.

Key ordering: objects are walked in SORTED key order in BOTH the collect
and apply walks. The round-trip is order-agnostic as long as both walks
use the identical order; sorting both keeps them aligned.
"""

from __future__ import annotations

import json

from apii.documents._base import (
    DocumentError,
    DocumentKind,
    ExtractedDoc,
    JsonPath,
    Segment,
)

# Inter-leaf separator in the detector-view text. ASCII record-separator
# (U+001E): no PII regex matches it as part of an entity, so detection
# spans can't cross leaf boundaries.
LEAF_SEP = "\x1e"


def _escape_pointer_segment(key: str) -> str:
    """RFC 6901: `~` -> `~0`, `/` -> `~1` (order matters: ~ first)."""
    return key.replace("~", "~0").replace("/", "~1")


def _walk_collect(value, path: str, text_parts: list[str], segments: list[Segment], cursor: list[int]) -> None:
    """Walk in deterministic order, collecting string LEAVES into the
    detector view + a segment per leaf. `cursor` is a one-element list
    tracking the running char length of the joined text."""
    if isinstance(value, str):
        start = cursor[0]
        end = start + len(value)
        text_parts.append(value)
        text_parts.append(LEAF_SEP)
        cursor[0] = end + len(LEAF_SEP)
        segments.append(Segment(text_range=(start, end), source=JsonPath(path)))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _walk_collect(item, f"{path}/{i}", text_parts, segments, cursor)
    elif isinstance(value, dict):
        # Sorted keys; the apply walk must use the same order.
        for k in sorted(value.keys()):
            _walk_collect(value[k], f"{path}/{_escape_pointer_segment(k)}", text_parts, segments, cursor)
    # Numbers / bools / None are not text and not PII candidates.


def _walk_apply(value, leaves: list[str], idx: list[int]):
    """Walk again in the same order, replacing each string leaf with the
    next entry from `leaves`. Returns the (possibly new) value so callers
    can rebind immutable str leaves into their parent container."""
    if isinstance(value, str):
        i = idx[0]
        idx[0] += 1
        if i < len(leaves):
            return leaves[i]
        return value
    if isinstance(value, list):
        for i in range(len(value)):
            value[i] = _walk_apply(value[i], leaves, idx)
        return value
    if isinstance(value, dict):
        for k in sorted(value.keys()):
            value[k] = _walk_apply(value[k], leaves, idx)
        return value
    return value


class JsonAdapter:
    @staticmethod
    def extract(data: bytes) -> ExtractedDoc:
        try:
            root = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            raise DocumentError(f"parse json: {e}") from e
        text_parts: list[str] = []
        segments: list[Segment] = []
        _walk_collect(root, "", text_parts, segments, [0])
        return ExtractedDoc(
            kind=DocumentKind.JSON,
            text="".join(text_parts),
            segments=segments,
        )

    @staticmethod
    def emit(data: bytes, extracted: ExtractedDoc, anonymized: str) -> bytes:
        # Re-parse the original to clone its structure, then walk it in
        # lockstep with the anonymized text (split on the same separator
        # extract joined string leaves with).
        try:
            root = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            raise DocumentError(f"parse json: {e}") from e

        if not anonymized:
            leaves: list[str] = []
        else:
            # extract appends LEAF_SEP after every leaf (incl. the last),
            # so trim a single trailing separator before splitting.
            trimmed = anonymized[: -len(LEAF_SEP)] if anonymized.endswith(LEAF_SEP) else anonymized
            leaves = trimmed.split(LEAF_SEP)

        idx = [0]
        root = _walk_apply(root, leaves, idx)
        if idx[0] != len(leaves):
            raise DocumentError(
                f"leaf count mismatch on emit: applied {idx[0]} of {len(leaves)}"
            )
        # ensure_ascii=False: corpus is Arabic-heavy; emit raw UTF-8 rather
        # than \uXXXX escapes.
        return json.dumps(root, indent=2, ensure_ascii=False).encode("utf-8")
