from __future__ import annotations

from typing import Iterator

import regex

from apii.types import Detection, EntityKind


class PatternRecognizer:
    """A recognizer backed by one compiled regular expression.

    Each non-overlapping match becomes a Detection stamped with this
    recognizer's kind, confidence, and source.

    Patterns are PyPI `regex` (not stdlib `re`): the Arabic recognizers
    need `\\p{Arabic}` property classes and `\\b` semantics that behave
    consistently across non-ASCII, neither of which stdlib offers. That
    import policy is applied uniformly so every recognizer's word-
    boundary behavior is identical.
    """

    requires_witness = False

    def __init__(
        self,
        name: str,
        kind: EntityKind,
        pattern: regex.Pattern[str],
        confidence: float,
        source: str,
    ) -> None:
        self.name = name
        self.kind = kind
        self.confidence = confidence
        self.source = source
        self._pattern = pattern

    def find(self, text: str) -> Iterator[Detection]:
        for m in self._pattern.finditer(text):
            yield Detection(
                start=m.start(),
                end=m.end(),
                kind=self.kind,
                text=m.group(),
                confidence=self.confidence,
                source=self.source,
            )
