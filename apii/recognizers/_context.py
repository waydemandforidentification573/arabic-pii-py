"""Shared helpers for context-capture and plain regex recognizers.

`context_capture` — the pattern's `(?P<v>...)` group is the entity, the
surrounding label is the cue. `regex_matches` — the entire match is the
entity, no label / no named group.

Per-kind validation gates live in each recognizer module; the surface
here is small and kind-agnostic so the two helpers compose cleanly.
"""

from __future__ import annotations

from typing import Callable, Iterator

import regex

from apii.types import Detection, EntityKind


def context_capture(
    pattern: regex.Pattern[str],
    text: str,
    kind: EntityKind,
    confidence: float,
    source: str,
    *,
    valid: Callable[[str], bool] | None = None,
    span_trim: Callable[[str, int, int], tuple[int, int]] | None = None,
) -> Iterator[Detection]:
    """Iterate matches of `pattern` and yield Detections over group `v`.

    `valid(value)` — optional, kind-specific gate (e.g. CR must contain a
    digit, Person stoplist). Returning False drops the match.

    `span_trim(text, start, end)` — optional, narrows the captured span
    (currently used only by Person to drop trailing whitespace and
    Arabic clitics).
    """
    for caps in pattern.finditer(text):
        try:
            start, end = caps.span("v")
        except IndexError:
            continue
        if start < 0 or end <= start:
            continue
        if span_trim is not None:
            start, end = span_trim(text, start, end)
            if start >= end:
                continue
        value = text[start:end]
        if not value.strip():
            continue
        if valid is not None and not valid(value):
            continue
        yield Detection(
            start=start,
            end=end,
            kind=kind,
            text=value,
            confidence=confidence,
            source=source,
        )


def regex_matches(
    pattern: regex.Pattern[str],
    text: str,
    kind: EntityKind,
    confidence: float,
    source: str,
    *,
    valid: Callable[[str], bool] | None = None,
    span_trim: Callable[[str, int, int], tuple[int, int]] | None = None,
) -> Iterator[Detection]:
    """Iterate matches of `pattern` and yield Detections over the full span.

    `valid(value)` — optional, kind-specific gate. Returning False drops
    the match. Used by ADDRESS (stoplist) and CR (digit-presence).

    `span_trim(text, start, end)` — optional, narrows the matched span
    (Organization uses it to drop trailing `IBAN SA…` / `VAT` / `CR`
    tails the org regex over-captured).
    """
    for m in pattern.finditer(text):
        start, end = m.start(), m.end()
        if span_trim is not None:
            start, end = span_trim(text, start, end)
            if start >= end:
                continue
        value = text[start:end]
        if not value.strip():
            continue
        if valid is not None and not valid(value):
            continue
        yield Detection(
            start=start,
            end=end,
            kind=kind,
            text=value,
            confidence=confidence,
            source=source,
        )
