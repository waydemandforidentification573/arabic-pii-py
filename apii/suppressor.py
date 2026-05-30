"""Common-phrase suppressor.

Drops detections whose surface text is plain structural vocabulary that
NER routinely mislabels as PII ("Position", "Total Amount", "Earth",
"Commercial Registration"). Loaded from a plain-text file:
  KIND:text   suppress only when tagged as KIND
  text        suppress regardless of kind
`#` comments + blank lines ignored; matching is case-insensitive on the
detection's surface text.

Activation is ENV-ONLY (APII_SUPPRESS_PHRASES) — no implicit default file,
so the pipeline stays deterministic unless an operator opts in by pointing
APII_SUPPRESS_PHRASES at a phrase file. This is NOT a name/org list — it is
structural vocabulary.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from apii.types import Detection, EntityKind

_KIND_ALIASES = {
    "PERSON": EntityKind.PERSON, "PER": EntityKind.PERSON,
    "ORG": EntityKind.ORGANIZATION, "ORGANIZATION": EntityKind.ORGANIZATION,
    "ADDRESS": EntityKind.ADDRESS, "LOC": EntityKind.ADDRESS, "LOCATION": EntityKind.ADDRESS,
    "PHONE": EntityKind.PHONE, "EMAIL": EntityKind.EMAIL, "IBAN": EntityKind.IBAN,
    "NATIONAL_ID": EntityKind.NATIONAL_ID,
    "GOV_ID": EntityKind.NATIONAL_ID, "COMMERCIAL_REGISTRATION": EntityKind.COMMERCIAL_REGISTRATION,
    "CR": EntityKind.COMMERCIAL_REGISTRATION,
    "TAX_NUMBER": EntityKind.TAX_NUMBER, "TAX_ID": EntityKind.TAX_NUMBER,
}


def _parse_kind(s: str) -> Optional[EntityKind]:
    return _KIND_ALIASES.get(s.strip().upper())


class Suppressor:
    """A set of (optional-kind, lowercased-text) suppression entries."""

    def __init__(self, entries: Optional[set[tuple[Optional[EntityKind], str]]] = None) -> None:
        self._entries = entries or set()

    @classmethod
    def from_text(cls, raw: str) -> "Suppressor":
        entries: set[tuple[Optional[EntityKind], str]] = set()
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, _, t = line.partition(":")
                kind = _parse_kind(k)
                if kind is None:
                    continue  # scoped to a kind apii doesn't emit → inert
                text = t.strip()
            else:
                kind, text = None, line
            if text:
                entries.add((kind, text.lower()))
        return cls(entries)

    @classmethod
    def load(cls, path: Path) -> "Suppressor":
        return cls.from_text(Path(path).read_text())

    def is_empty(self) -> bool:
        return not self._entries

    def size(self) -> int:
        return len(self._entries)

    def filter(self, detections: list[Detection]) -> list[Detection]:
        if not self._entries:
            return detections
        out = []
        for d in detections:
            low = d.text.lower()
            if (None, low) in self._entries or (d.kind, low) in self._entries:
                continue
            out.append(d)
        return out


# ── process-wide handle (env-only, swappable for tests) ──

_GLOBAL: list[Optional[Suppressor]] = []


def set_global(s: Optional[Suppressor]) -> None:
    _GLOBAL[:] = [s]


def current() -> Suppressor:
    if not _GLOBAL:
        path = os.environ.get("APII_SUPPRESS_PHRASES")
        if path and Path(path).exists():
            try:
                _GLOBAL.append(Suppressor.load(Path(path)))
            except OSError:
                _GLOBAL.append(Suppressor())
        else:
            _GLOBAL.append(Suppressor())
    return _GLOBAL[0] or Suppressor()
