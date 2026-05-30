from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from apii.types import Detection, EntityKind


@runtime_checkable
class Recognizer(Protocol):
    """A stateless detector for one entity kind.

    Implementations stamp their own `kind`, `confidence`, and `source`
    onto every Detection they yield. `requires_witness` marks a
    recognizer whose hits are only kept when an independent recognizer of
    the same kind overlaps them — the gate that keeps NER from emitting
    lone, unsupported spans.
    """

    name: str
    kind: EntityKind
    confidence: float
    requires_witness: bool

    def find(self, text: str) -> Iterable[Detection]: ...
