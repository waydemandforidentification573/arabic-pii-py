"""Span replacement helpers.

`replace_spans` applies (start, end, replacement) edits right-to-left so
earlier edits don't shift later offsets. `replace_longest_first`
substitutes literal needles longest-first so a token that is a prefix of
another (PERSON_AAAA vs PERSON_AAAA_BBBB) doesn't corrupt the longer one.
Offsets are Python str char indices.
"""

from __future__ import annotations


def replace_spans(text: str, replacements: list[tuple[int, int, str]]) -> str:
    """Apply (start, end, replacement) edits, right-to-left."""
    out = text
    for start, end, replacement in sorted(replacements, key=lambda r: r[0], reverse=True):
        out = out[:start] + replacement + out[end:]
    return out


def replace_longest_first(
    text: str, replacements: list[tuple[str, str]]
) -> tuple[str, list[tuple[str, int]]]:
    """Replace literal `needle`→`value` pairs, longest needle first.

    Returns (output, hits) where hits is [(needle, count), …] for needles
    that matched.
    """
    out = text
    hits: list[tuple[str, int]] = []
    for needle, value in sorted(replacements, key=lambda r: len(r[0]), reverse=True):
        if not needle:
            continue
        count = out.count(needle)
        if count == 0:
            continue
        out = out.replace(needle, value)
        hits.append((needle, count))
    return out, hits
